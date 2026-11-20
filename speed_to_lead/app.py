"""FastAPI service: Meta webhooks (WhatsApp + Lead Ads), website form, staff pages, cron tick, dashboard.

No `from __future__ import annotations` here: FastAPI must see the local `Staff` dependency at runtime.
"""

import asyncio
import json
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from . import dashboard, metrics, sla, web
from .config import Settings
from .db import Store, iso
from .notify import Notifier
from .pipeline import Clock, Pipeline, utcnow
from .whatsapp import Sender, WhatsAppClient, fetch_leadgen, parse_leadgen, parse_messages, verify_signature

basic = HTTPBasic()


def create_app(
    s: Settings,
    store: Store | None = None,
    wa: Sender | None = None,
    notifier: Notifier | None = None,
    clock: Clock = utcnow,
    leadgen: Callable[[str], dict[str, Any]] | None = None,
) -> FastAPI:
    store = store or Store(s.database_url)
    store.migrate()
    wa = wa or WhatsAppClient(s)
    notifier = notifier or Notifier(s, store, wa)
    p = Pipeline(s, store, wa, notifier, clock, leadgen or (lambda lid: fetch_leadgen(s, lid)))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = None
        if s.sla_loop_seconds > 0:

            async def loop() -> None:
                while True:
                    await asyncio.sleep(s.sla_loop_seconds)
                    await asyncio.to_thread(sla.tick, p, p.clock())

            task = asyncio.create_task(loop())
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="speed-to-lead", lifespan=lifespan)
    app.state.pipeline = p
    origins = [o.strip() for o in s.form_allowed_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["POST"], allow_headers=["*"])

    def staff(creds: Annotated[HTTPBasicCredentials, Depends(basic)]) -> str:
        if not s.staff_password:
            raise HTTPException(503, "Set STL_STAFF_PASSWORD to enable staff pages")
        ok = secrets.compare_digest(
            creds.username.encode(), s.staff_user.encode()
        ) and secrets.compare_digest(creds.password.encode(), s.staff_password.encode())
        if not ok:
            raise HTTPException(401, "bad credentials", headers={"WWW-Authenticate": "Basic"})
        return creds.username

    Staff = Annotated[str, Depends(staff)]

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"ok": True, "dry_run": s.dry_run, "db": store.dialect}

    # -- Meta webhooks (WhatsApp Business Account + Page leadgen share one callback URL) -------
    @app.get("/webhooks/meta", response_class=PlainTextResponse)
    def verify(request: Request) -> str:
        q = request.query_params
        if (
            q.get("hub.mode") == "subscribe"
            and s.wa_verify_token
            and secrets.compare_digest(q.get("hub.verify_token", ""), s.wa_verify_token)
        ):
            return q.get("hub.challenge", "")
        raise HTTPException(403, "verification failed")

    @app.post("/webhooks/meta")
    async def meta_webhook(request: Request, bg: BackgroundTasks) -> dict[str, Any]:
        raw = await request.body()
        if not verify_signature(s.wa_app_secret, raw, request.headers.get("X-Hub-Signature-256")):
            raise HTTPException(403, "bad signature")
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise HTTPException(400, "bad json") from exc
        msgs, leads = parse_messages(payload), parse_leadgen(payload)
        for m in msgs:
            bg.add_task(p.handle_whatsapp, m)
        for v in leads:
            bg.add_task(p.handle_leadgen, v)
        return {"received": len(msgs) + len(leads)}  # 200 fast; work runs right after the response

    # -- website / landing-page form ------------------------------------------------------
    @app.post("/webhooks/form")
    async def form(request: Request) -> dict[str, Any]:
        if request.headers.get("content-type", "").startswith("application/json"):
            data: dict[str, Any] = await request.json()
        else:
            data = dict(await request.form())
        if data.get("website"):  # honeypot field hidden from humans
            return {"ok": True}
        consent = str(data.get("consent", "")).lower() in {"1", "true", "on", "yes"}
        if not consent:
            raise HTTPException(422, "consent checkbox is required")
        try:
            _, link = p.handle_form(
                str(data.get("phone", "")),
                str(data.get("name", "")) or None,
                str(data.get("message", ""))[:2000],
                consent,
                detail=str(data.get("utm_source", "")) or None,
                submission_id=str(data.get("submission_id", "")) or None,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"ok": True, "whatsapp_link": link}

    # -- cron / SLA ------------------------------------------------------------------------
    @app.post("/cron/tick")
    def cron(request: Request) -> dict[str, Any]:
        sent = request.headers.get("X-Cron-Secret", "")
        if not s.cron_secret or not secrets.compare_digest(sent, s.cron_secret):
            raise HTTPException(403, "bad cron secret")
        return {"actions": sla.tick(p, p.clock())}

    # -- public anonymised dashboard -------------------------------------------------------
    @app.get("/dashboard", response_class=HTMLResponse)
    def dash() -> str:
        m = metrics.compute(store, s)
        return dashboard.render(m, status_line(m), iso(p.clock()))

    # -- staff pages -----------------------------------------------------------------------
    @app.get("/staff", response_class=HTMLResponse)
    def staff_home(_: Staff) -> str:
        rows = [r for r in store.leads() if r["status"] not in ("won", "lost")][:200]
        return web.lead_list(rows)

    @app.get("/staff/lead/{lead_id}", response_class=HTMLResponse)
    def staff_lead(lead_id: str, _: Staff) -> str:
        r = store.get_lead(lead_id)
        if not r:
            raise HTTPException(404)
        return web.lead_detail(r, store.events(lead_id), p.window_open(r, p.clock()))

    @app.post("/staff/lead/{lead_id}/action")
    async def staff_action(lead_id: str, request: Request, user: Staff) -> Response:
        f = await request.form()
        action = str(f.get("action", ""))
        raw = str(f.get("value", "")).replace(",", "").replace("₹", "").strip()
        value = int(float(raw)) if raw else None
        text = str(f.get("text", "") or f.get("lost_reason", "")) or None
        try:
            await asyncio.to_thread(p.human_action, lead_id, action, user, value, text)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return RedirectResponse(f"/staff/lead/{lead_id}", status_code=303)

    @app.get("/staff/new", response_class=HTMLResponse)
    def staff_new(_: Staff) -> str:
        return web.manual_form()

    @app.post("/staff/new", response_class=HTMLResponse)
    async def staff_new_post(request: Request, user: Staff) -> str:
        f = await request.form()
        try:
            p.handle_manual(
                str(f.get("phone", "")),
                str(f.get("name", "")) or None,
                str(f.get("source", "other")),
                str(f.get("notes", "")),
                f.get("consent") == "1",
                f.get("responded") == "1",
                user,
                {"project_type": str(f.get("project_type", "")), "area": str(f.get("area", ""))},
            )
        except ValueError:
            return web.manual_form("Invalid phone number / नंबर गलत है")
        return web.manual_form("Saved ✅ / सेव हो गया")

    @app.get("/staff/baseline", response_class=HTMLResponse)
    def baseline_get(_: Staff) -> str:
        return web.baseline_form(len(store.baseline(include_synthetic=False)))

    @app.post("/staff/baseline", response_class=HTMLResponse)
    async def baseline_post(request: Request, user: Staff) -> str:
        f = await request.form()
        tz = ZoneInfo(s.timezone)

        def dt(k: str) -> datetime | None:
            v = str(f.get(k, ""))
            return datetime.fromisoformat(v).replace(tzinfo=tz) if v else None

        def num(k: str) -> int | None:
            v = str(f.get(k, "")).replace(",", "").strip()
            return int(float(v)) if v else None

        lead_at = dt("lead_at")
        if lead_at is None:
            return web.baseline_form(len(store.baseline(False)), "Enquiry time is required")
        store.add_baseline(
            str(f.get("source", "other")),
            lead_at,
            dt("first_reply_at"),
            str(f.get("outcome", "open")),
            num("quote_value"),
            num("invoice_value"),
            str(f.get("notes", "")) or None,
            str(f.get("logged_by", "")) or user,
            p.clock(),
        )
        return web.baseline_form(len(store.baseline(False)), "Saved ✅")

    @app.get("/staff/baseline.csv", response_class=PlainTextResponse)
    def baseline_csv(_: Staff) -> str:
        cols = [
            "source",
            "lead_at",
            "first_reply_at",
            "outcome",
            "quote_value",
            "invoice_value",
            "notes",
            "logged_by",
        ]
        return web.to_csv(store.baseline(False), cols)

    return app


def status_line(m: dict[str, Any]) -> str:
    b = m["before_after"]["baseline"]
    if m["synthetic"]:
        return "Synthetic demo run — proves the pipeline, not business results."
    if b["leads"] == 0 and m["leads_total"] == 0:
        return "Week 0 — baseline logging not started. This page fills as real enquiries are logged."
    if m["leads_total"] == 0:
        return (
            f"Baseline in progress: {b['days_logged']} of 14 days logged ({b['leads']} enquiries). "
            "System not live yet."
        )
    return (
        f"Live: {m['leads_total']} leads tracked; baseline {b['days_logged']} days / {b['leads']} enquiries."
    )
