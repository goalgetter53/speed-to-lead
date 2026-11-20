"""End-to-end simulation: fake Meta + Telegram server, the real FastAPI service over real HTTP, and
clearly-labelled SYNTHETIC leads. Proves <60 s first response and SLA alerts. Writes demo_output/.

Nothing here is a business result. All leads are named "SYNTHETIC ..." and flagged synthetic=1.
"""

from __future__ import annotations

import json
import random
import socket
import statistics
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import uvicorn

from . import dashboard, metrics, sla
from .app import create_app, status_line
from .config import Settings
from .db import iso
from .fake_meta import FakeMeta
from .pipeline import Pipeline
from .whatsapp import sign

IST = ZoneInfo("Asia/Kolkata")
OUT = Path("demo_output")


class SimClock:
    """Simulated wall clock that still advances in real time, so measured latencies are real."""

    def __init__(self, start: datetime) -> None:
        self.set(start)

    def set(self, dt: datetime) -> None:
        self._base, self._t0 = dt, time.monotonic()

    def __call__(self) -> datetime:
        return self._base + timedelta(seconds=time.monotonic() - self._t0)


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _serve(app: Any, port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError("server did not start")


# Synthetic WhatsApp enquiries (wa_id, text, referral). Numbers are fake and never leave this machine.
WA_LEADS: list[tuple[str, str, str, dict[str, Any]]] = [
    (
        "SYNTHETIC 01 Hindi seepage",
        "919000000001",
        "नमस्ते, छत से पानी टपक रहा है, सीलन बहुत है। Undri 411060, 2BHK. waterproofing ka rate kitna hai? jaldi chahiye",
        {},
    ),
    (
        "SYNTHETIC 02 English interior",
        "919000000002",
        "Hi, need Asian Paints Royale rate for 3BHK interior in NIBM, my flat, planning before Diwali",
        {},
    ),
    (
        "SYNTHETIC 03 Marathi exterior",
        "919000000003",
        "नमस्कार, आमच्या बंगल्याचे बाहेरील रंगकाम करायचे आहे, Pisoli मध्ये. किती खर्च येईल?",
        {},
    ),
    (
        "SYNTHETIC 04 CTWA ad",
        "919000000004",
        "Hi, I saw your ad. Wood polish for 4 doors",
        {"source_type": "ad", "source_id": "SYNTHETIC-AD-1", "headline": "Diwali paint offer"},
    ),
    (
        "SYNTHETIC 05 contractor",
        "919000000005",
        "Painter hoon, Kondhwa site ke liye bulk Tractor emulsion 200 litre dealer rate chahiye",
        {},
    ),
    (
        "SYNTHETIC 06 Google Maps",
        "919000000006",
        "Hi United Trader, enquiry (ref:gbp) exterior paint price",
        {},
    ),
    ("SYNTHETIC 07 far away", "919000000007", "Need waterproofing in Hinjewadi 411057", {}),
]


def wa_payload(name: str, wa_id: str, text: str, ts: datetime, wamid: str, referral: dict[str, Any]) -> bytes:
    msg: dict[str, Any] = {
        "from": wa_id,
        "id": wamid,
        "timestamp": str(int(ts.timestamp())),
        "type": "text",
        "text": {"body": text},
    }
    if referral:
        msg["referral"] = referral
    body = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "SYNTH"},
                            "contacts": [{"wa_id": wa_id, "profile": {"name": name}}],
                            "messages": [msg],
                        },
                    }
                ],
            }
        ],
    }
    return json.dumps(body, ensure_ascii=False).encode()


def run() -> int:
    OUT.mkdir(exist_ok=True)
    db_path = OUT / "demo.db"
    for f in OUT.glob("demo.db*"):
        f.unlink()
    fake = FakeMeta()
    fport, aport = _port(), _port()
    s = Settings(
        database_url=f"sqlite:///{db_path}",
        dry_run=False,
        graph_base_url=f"http://127.0.0.1:{fport}",
        telegram_base_url=f"http://127.0.0.1:{fport}",
        telegram_bot_token="demo",
        telegram_father_chat="1",
        telegram_painter_chat="2",
        telegram_hussain_chat="3",
        wa_app_secret="demo-app-secret",
        wa_verify_token="demo-verify",
        wa_access_token="demo-token",
        wa_phone_number_id="SYNTH",
        wa_business_number="910000000000",
        catalogue_url="https://example.com/price-list",
        synthetic_mode=True,
        sla_loop_seconds=0,
        cron_secret="demo-cron",
        staff_password="demo",
        public_base_url=f"http://127.0.0.1:{aport}",
    )
    clock = SimClock(datetime(2026, 11, 17, 11, 0, tzinfo=IST))  # a Tuesday, shop open
    app = create_app(s, clock=clock)
    p: Pipeline = app.state.pipeline
    _serve(fake.app(), fport)
    _serve(app, aport)
    base = f"http://127.0.0.1:{aport}"
    http = httpx.Client(base_url=base, timeout=10)
    checks: dict[str, bool] = {}
    log: list[str] = []

    def post_wa(raw: bytes) -> httpx.Response:
        return http.post(
            "/webhooks/meta",
            content=raw,
            headers={"X-Hub-Signature-256": sign(s.wa_app_secret, raw), "Content-Type": "application/json"},
        )

    def wait_until(cond: Any, timeout: float = 10.0) -> bool:
        t_end = time.perf_counter() + timeout
        while time.perf_counter() < t_end:
            if cond():
                return True
            time.sleep(0.005)
        return False

    def wait_reply(wa_id: str, n: int, timeout: float = 60.0) -> float | None:
        t_end = time.perf_counter() + timeout
        while time.perf_counter() < t_end:
            if len(fake.sent_to(wa_id)) >= n:
                return float(fake.sent_to(wa_id)[n - 1]["t"])
            time.sleep(0.005)
        return None

    # 1. webhook verification + signature check
    r = http.get(
        "/webhooks/meta",
        params={"hub.mode": "subscribe", "hub.verify_token": "demo-verify", "hub.challenge": "1234"},
    )
    checks["verify_token_handshake"] = r.text == "1234"
    bad = wa_payload("x", "919000000099", "hi", clock(), "wamid.BAD", {})
    checks["bad_signature_rejected"] = (
        http.post("/webhooks/meta", content=bad, headers={"X-Hub-Signature-256": "sha256=00"}).status_code
        == 403
    )

    # 2. WhatsApp leads in shop hours: measure webhook POST -> message accepted by (fake) Meta
    latencies: list[float] = []
    for i, (name, wa_id, text, ref) in enumerate(WA_LEADS):
        raw = wa_payload(name, wa_id, text, clock(), f"wamid.SYN{i:02d}", ref)
        t0 = time.perf_counter()
        post_wa(raw)
        t1 = wait_reply(wa_id, 1)
        latencies.append(round(t1 - t0, 3) if t1 else 999.0)
    checks["all_first_replies_under_60s"] = all(x < 60 for x in latencies)
    log.append(f"first-reply latency (s) per synthetic WhatsApp lead: {latencies}")

    # 3. Meta redelivers the same webhook -> no second reply
    name, wa_id, text, ref = WA_LEADS[0]
    post_wa(wa_payload(name, wa_id, text, clock(), "wamid.SYN00", ref))
    time.sleep(0.5)  # give a wrongly-processed duplicate time to show up
    checks["duplicate_webhook_ignored"] = len(fake.sent_to(wa_id)) == 1

    # 4. STOP -> opted out, one confirmation, nothing after
    post_wa(wa_payload(WA_LEADS[6][0], WA_LEADS[6][1], "STOP", clock(), "wamid.STOP7", {}))
    wait_reply(WA_LEADS[6][1], 2, 5)
    checks["stop_confirmed"] = len(fake.sent_to(WA_LEADS[6][1])) == 2

    # 5. Meta lead ad (Instagram) -> no free WhatsApp window -> owner told to CALL NOW
    fake.leads["SYN-LEADGEN-1"] = {
        "id": "SYN-LEADGEN-1",
        "created_time": iso(clock()),
        "platform": "ig",
        "form_id": "SYN-FORM",
        "ad_id": "SYN-AD-2",
        "field_data": [
            {"name": "full_name", "values": ["SYNTHETIC 08 IG lead form"]},
            {"name": "phone_number", "values": ["+91 90000 00008"]},
            {"name": "what_work", "values": ["exterior painting, row house"]},
            {"name": "when_to_start", "values": ["this month"]},
            {"name": "post_code", "values": ["411028"]},
            {"name": "whatsapp_opt_in", "values": ["yes"]},
        ],
    }
    lg = json.dumps(
        {
            "object": "page",
            "entry": [
                {
                    "id": "PAGE",
                    "time": 0,
                    "changes": [
                        {
                            "field": "leadgen",
                            "value": {
                                "leadgen_id": "SYN-LEADGEN-1",
                                "page_id": "PAGE",
                                "form_id": "SYN-FORM",
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()
    n_tg = len(fake.telegram)
    http.post("/webhooks/meta", content=lg, headers={"X-Hub-Signature-256": sign(s.wa_app_secret, lg)})
    checks["leadgen_owner_call_alert"] = wait_until(
        lambda: any("CALL NOW" in str(m["text"]) for m in fake.telegram[n_tg:])
    )

    # 6. Website form and a manual walk-in entry by staff
    fr = http.post(
        "/webhooks/form",
        json={
            "phone": "9000000009",
            "name": "SYNTHETIC 09 website form",
            "message": "Need wood polish for furniture, Mohammadwadi",
            "consent": True,
        },
    )
    checks["website_form_returns_wa_link"] = fr.json().get("whatsapp_link", "").startswith("https://wa.me/")
    mr = http.post(
        "/staff/new",
        auth=("staff", "demo"),
        data={
            "phone": "9000000010",
            "name": "SYNTHETIC 10 walk-in",
            "source": "walk_in",
            "project_type": "interior",
            "area": "Undri",
            "notes": "2BHK, Apcolite, wants quote tomorrow",
            "responded": "1",
        },
    )
    checks["manual_walk_in_saved"] = mr.status_code == 200 and "Saved" in mr.text

    # 7. Humans reply to some leads; SLA alerts for the rest
    lid = {name: store_id for name, store_id in ((r["name"], r["id"]) for r in p.store.leads())}
    clock.set(datetime(2026, 11, 17, 11, 3, tzinfo=IST))
    p.human_action(lid["SYNTHETIC 02 English interior"], "replied", "demo-staff")
    clock.set(datetime(2026, 11, 17, 11, 6, tzinfo=IST))
    sla1 = sla.tick(p, clock())
    clock.set(datetime(2026, 11, 17, 11, 8, tzinfo=IST))
    p.human_action(lid["SYNTHETIC 05 contractor"], "replied", "demo-staff")
    clock.set(datetime(2026, 11, 17, 11, 16, tzinfo=IST))
    sla2 = sla.tick(p, clock())
    checks["sla_5min_alerts_fired"] = sum(a.startswith("sla1") for a in sla1) >= 4
    checks["replied_lead_not_alerted"] = not any(lid["SYNTHETIC 02 English interior"] in a for a in sla1)
    checks["sla_15min_escalations_fired"] = sum(a.startswith("sla2") for a in sla2) >= 3
    log.append(f"SLA tick 11:06 IST -> {len(sla1)} alerts; 11:16 IST -> {len(sla2)} escalations")

    # 8. Follow-up inside the free 24h window, never to the opted-out lead
    clock.set(datetime(2026, 11, 17, 13, 5, tzinfo=IST))
    fu = sla.tick(p, clock())
    checks["followups_sent"] = any(a.startswith("fu:") for a in fu)
    checks["no_followup_to_opted_out"] = len(fake.sent_to(WA_LEADS[6][1])) == 2

    # 9. Out of hours: auto-acknowledge with next opening time; SLA clock waits for opening
    clock.set(datetime(2026, 11, 17, 23, 10, tzinfo=IST))
    wa_oh = "919000000011"
    t0 = time.perf_counter()
    post_wa(
        wa_payload(
            "SYNTHETIC 11 night enquiry",
            wa_oh,
            "Hello, need paint for 1BHK in Handewadi",
            clock(),
            "wamid.SYN11",
            {},
        )
    )
    t1 = wait_reply(wa_oh, 1)
    latencies.append(round(t1 - t0, 3) if t1 else 999.0)
    night_text = fake.sent_to(wa_oh)[0]["payload"]["text"]["body"] if t1 else ""
    checks["out_of_hours_ack_with_next_open"] = "closed" in night_text and "tomorrow at 9:30 AM" in night_text
    clock.set(datetime(2026, 11, 17, 23, 20, tzinfo=IST))
    night = sla.tick(p, clock())
    checks["no_sla_alert_while_closed"] = not any(a.startswith("sla1") for a in night)
    clock.set(datetime(2026, 11, 18, 9, 36, tzinfo=IST))
    morning = sla.tick(p, clock())
    checks["sla_alert_after_opening"] = any(a.startswith("sla1") for a in morning)

    # 10. Outcomes (synthetic) and a synthetic baseline so before/after renders
    clock.set(datetime(2026, 11, 18, 12, 0, tzinfo=IST))
    for nm, quote, won in (
        ("SYNTHETIC 01 Hindi seepage", 18500, 17800),
        ("SYNTHETIC 05 contractor", 64000, 64000),
        ("SYNTHETIC 02 English interior", 42000, None),
        ("SYNTHETIC 10 walk-in", 9000, 8700),
    ):
        p.human_action(lid[nm], "quote", "demo-staff", quote)
        if won:
            p.human_action(lid[nm], "won", "demo-staff", won)
    rng = random.Random(7)
    for d in range(14):
        for _ in range(rng.randint(2, 4)):
            at = datetime(2026, 11, 1 + d, rng.randint(10, 19), rng.randint(0, 59), tzinfo=IST)
            reply = (
                None
                if rng.random() < 0.15
                else at + timedelta(minutes=rng.choice([2, 8, 15, 35, 70, 180, 600]))
            )
            outcome = rng.choice(["open", "quoted", "lost", "lost", "won"])
            p.store.add_baseline(
                rng.choice(["whatsapp", "walk_in", "phone_call", "gbp_call"]),
                at,
                reply,
                outcome,
                None,
                rng.choice([6000, 12000, 25000]) if outcome == "won" else None,
                "SYNTHETIC baseline row",
                "demo",
                clock(),
                synthetic=True,
            )

    m = metrics.compute(p.store, s, synthetic=True)
    checks["dashboard_has_no_phone_numbers"] = True
    html = dashboard.render(m, status_line(m), iso(clock()))
    checks["dashboard_has_no_phone_numbers"] = "900000000" not in html and "SYNTHETIC 0" not in html
    (OUT / "dashboard_synthetic.html").write_text(html, encoding="utf-8")
    report = {
        "label": "SYNTHETIC DEMO — not business results",
        "checks": checks,
        "wa_first_reply_latency_s": {
            "values": latencies,
            "median": statistics.median(latencies),
            "max": max(latencies),
        },
        "whatsapp_messages_sent_to_fake_meta": len(fake.sent),
        "owner_alerts_sent_to_fake_telegram": len(fake.telegram),
        "metrics": m,
        "log": log,
    }
    (OUT / "demo_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print("SYNTHETIC DEMO — fake WhatsApp/Telegram server, synthetic leads, real HTTP + real pipeline")
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    print(
        f"  first-reply latency over {len(latencies)} WhatsApp leads: median {statistics.median(latencies):.3f} s, "
        f"max {max(latencies):.3f} s (target < 60 s)"
    )
    print(f"  WhatsApp messages sent: {len(fake.sent)}; owner alerts: {len(fake.telegram)}")
    print(f"  wrote {OUT}/demo_report.json and {OUT}/dashboard_synthetic.html")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(run())
