"""Lead in -> enrich -> score -> route -> first response -> owner notification. One class, plain calls."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from . import hours, messages
from .config import OWNER_KEYS, Settings
from .db import Row, Store, iso, parse_iso
from .enrich import enrich, llm_classify, merge_into_lead
from .notify import Notifier
from .phone import normalise
from .routing import route
from .scoring import score
from .whatsapp import Inbound, Sender, SendResult, leadgen_fields

Clock = Callable[[], datetime]
YES = {"yes", "y", "true", "1", "haan", "ha", "हाँ", "हो", "होय", "agree", "i agree"}
WINDOW = timedelta(hours=24)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Pipeline:
    def __init__(
        self,
        s: Settings,
        store: Store,
        wa: Sender,
        notifier: Notifier,
        clock: Clock = utcnow,
        fetch_leadgen: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.s, self.store, self.wa, self.notifier, self.clock = s, store, wa, notifier, clock
        self.fetch_leadgen = fetch_leadgen

    # -- helpers ---------------------------------------------------------------------------
    def owner_for_phone(self, e164: str) -> str | None:
        for o in OWNER_KEYS:
            if normalise(self.s.owner_wa(o)) == e164:
                return o
        return None

    def lead(self, lead_id: str) -> Row:
        row = self.store.get_lead(lead_id)
        if row is None:
            raise KeyError(lead_id)
        return row

    def link(self, lead_id: str) -> str:
        return f"{self.s.public_base_url}/staff/lead/{lead_id}"

    def window_open(self, lead: Row, now: datetime) -> bool:
        last = lead.get("last_inbound_at")
        return bool(last) and now - parse_iso(str(last)) < WINDOW

    def monthly_outbound(self, now: datetime) -> int:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rows = self.store.query(
            "SELECT COUNT(*) AS n FROM events WHERE channel = 'whatsapp_out' AND at >= ?", (iso(start),)
        )
        return int(rows[0]["n"])

    def wa_me_link(self, ref: str) -> str:
        text = quote(f"Hi {self.s.shop_name}, enquiry {ref}")
        return f"https://wa.me/{self.s.wa_business_number}?text={text}"

    def process(self, lead_id: str) -> Row:
        """Re-enrich from all inbound text, re-score, route once. Idempotent."""
        lead = self.lead(lead_id)
        texts = [e["body"] or "" for e in self.store.events(lead_id) if e["kind"] == "inbound"]
        text = "\n".join(texts)
        e = enrich(text, self.s)
        llm = llm_classify(text, self.s) if self.s.llm_api_key else {}
        upd = merge_into_lead(lead, e, llm)
        merged = {**lead, **upd}
        sc, bucket, lines = score(merged, e)
        upd.update(score=sc, score_bucket=bucket, score_explain=json.dumps(lines, ensure_ascii=False))
        if not lead.get("owner"):
            owner, why = route(merged, bucket)
            upd.update(owner=owner, route_reason=why)
        self.store.update_lead(lead_id, **upd)
        return self.lead(lead_id)

    def send_session(
        self,
        lead: Row,
        body: str,
        kind: str,
        key: str,
        now: datetime,
        t0: float | None = None,
        actor: str = "bot",
    ) -> SendResult | None:
        """Free-form WhatsApp message; only inside the customer's 24h window, never to opted-out numbers."""
        if lead.get("opted_out") and kind not in ("system",):
            return None
        if not self.window_open(lead, now):
            return None
        if self.monthly_outbound(now) >= self.s.service_msg_monthly_cap:
            self.store.add_event(
                lead["id"], "note", f"cap:{key}", now, body="monthly free-message cap reached"
            )
            self.notifier.notify(
                "hussain", "WhatsApp monthly free-message cap reached; automation paused.", now
            )
            return None
        res = self.wa.send_text(str(lead["phone"]), body)
        sent = self.clock()
        meta: dict[str, Any] = {
            "ok": res.ok,
            "message_id": res.message_id,
            "error": res.error,
            "dry_run": res.dry_run,
        }
        if t0 is not None:
            meta["pipeline_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        self.store.add_event(
            lead["id"], kind, key, sent, channel="whatsapp_out", actor=actor, body=body, meta=meta
        )
        if res.ok and kind == "auto_reply" and not lead.get("first_auto_reply_at"):
            self.store.update_lead(lead["id"], first_auto_reply_at=iso(sent))
        return res

    def alert(self, lead: Row, kind: str, key: str, now: datetime, owner: str | None = None) -> bool:
        if not self.store.add_event(
            lead["id"], "alert", key, now, channel="owner", actor=owner or lead["owner"], body=kind
        ):
            return False
        open_now = hours.is_open(now, self.s)
        text = messages.owner_alert(lead, kind, self.link(lead["id"]), open_now)
        self.notifier.notify(owner or str(lead["owner"] or "father"), text, now, silent=not open_now)
        return True

    def _needs_first_reply(self, lead_id: str, now: datetime) -> bool:
        rows = self.store.query(
            "SELECT MAX(at) AS last FROM events WHERE lead_id = ? AND kind IN ('auto_reply', 'human_reply')",
            (lead_id,),
        )
        last = rows[0]["last"]
        return last is None or now - parse_iso(str(last)) >= WINDOW

    # -- sources ---------------------------------------------------------------------------
    def handle_whatsapp(self, msg: Inbound) -> str:
        t0 = time.perf_counter()
        now = self.clock()
        phone = normalise("+" + msg.wa_from.lstrip("+"))
        if not phone:
            return "bad_phone"
        owner = self.owner_for_phone(phone)
        if owner:
            self.store.owner_ping(owner, now)
            return "owner_ping"
        source, detail = msg.source()
        lead_id, _ = self.store.upsert_lead(
            phone, source, now, name=msg.name, source_detail=detail, synthetic=self.s.synthetic_mode
        )
        meta = {"platform_ts": iso(msg.timestamp), "type": msg.msg_type, "referral": msg.referral or None}
        if not self.store.add_event(
            lead_id, "inbound", "wa:" + msg.wamid, now, channel="whatsapp", body=msg.text, meta=meta
        ):
            return "duplicate"
        lead = self.lead(lead_id)
        upd: dict[str, Any] = {"last_inbound_at": iso(now)}
        if not lead.get("consent_source"):
            upd.update(consent_source="customer_initiated_whatsapp", consent_at=iso(now))
        self.store.update_lead(lead_id, **upd)
        lead = self.lead(lead_id)
        lang = lead.get("language") or "en"
        if messages.is_opt_out(msg.text):
            self.store.update_lead(lead_id, opted_out=1, opted_out_at=iso(now))
            self.store.add_event(lead_id, "opt_out", "optout:" + msg.wamid, now, channel="whatsapp")
            self.send_session(
                self.lead(lead_id),
                messages.OPT_OUT_CONFIRM[lang],
                "system",
                "optout-confirm:" + msg.wamid,
                now,
            )
            return "opted_out"
        if messages.is_opt_in(msg.text) and lead.get("opted_out"):
            self.store.update_lead(lead_id, opted_out=0)
            self.store.add_event(lead_id, "opt_in", "optin:" + msg.wamid, now, channel="whatsapp")
            self.send_session(
                self.lead(lead_id), messages.OPT_IN_CONFIRM[lang], "system", "optin-confirm:" + msg.wamid, now
            )
            return "opted_in"
        if lead.get("opted_out"):
            return "ignored_opted_out"
        lead = self.process(lead_id)
        if not self._needs_first_reply(lead_id, now):
            return "conversation_continues"
        open_now = hours.is_open(now, self.s)
        lang = str(lead.get("language") or "en")
        nxt = hours.describe_next_open(hours.next_open(now, self.s), now, self.s, lang)
        body = messages.first_reply(lead, lang, self.s.shop_name, self.s.catalogue_url, open_now, nxt)
        self.send_session(lead, body, "auto_reply", "auto:" + msg.wamid, now, t0=t0)
        self.alert(self.lead(lead_id), "new", "notify:new:" + msg.wamid, now)
        return "replied" if open_now else "replied_out_of_hours"

    def handle_leadgen(self, value: dict[str, Any]) -> str:
        leadgen_id = str(value.get("leadgen_id", ""))
        if not leadgen_id or self.store.has_event("leadgen:" + leadgen_id):
            return "duplicate"
        if self.fetch_leadgen is None:
            return "no_fetcher"
        data = self.fetch_leadgen(leadgen_id)
        f = leadgen_fields(data)
        phone = normalise(f.get("phone_number") or f.get("phone"))
        if not phone:
            return "no_phone"
        now = self.clock()
        platform = str(data.get("platform") or "fb")
        detail = f"{platform}:form={data.get('form_id') or value.get('form_id')}:ad={data.get('ad_id') or ''}"
        lead_id, _ = self.store.upsert_lead(
            phone,
            "meta_lead_ad",
            now,
            name=f.get("full_name") or None,
            source_detail=detail,
            synthetic=self.s.synthetic_mode,
        )
        skip = {"phone_number", "phone", "full_name", "email", self.s.leadform_optin_field}
        answers = "\n".join(v for k, v in f.items() if k not in skip and v)
        if not self.store.add_event(
            lead_id,
            "inbound",
            "leadgen:" + leadgen_id,
            now,
            channel="meta_lead_ad",
            body=answers,
            meta={"platform": platform},
        ):
            return "duplicate"
        lead = self.lead(lead_id)
        if f.get(self.s.leadform_optin_field, "").strip().lower() in YES and not lead.get("consent_source"):
            self.store.update_lead(lead_id, consent_source="meta_lead_form_optin", consent_at=iso(now))
        lead = self.process(lead_id)
        # No WhatsApp window exists for form leads. Free path: a human calls (alert). Paid path is opt-in.
        if self.s.allow_paid_templates and lead.get("consent_source") and not lead.get("opted_out"):
            res = self.wa.send_template(
                str(lead["phone"]),
                "ut_enquiry_received",
                "en",
                [
                    str(lead.get("name") or "there"),
                    str(lead.get("project_type") or "paint"),
                    "shortly",
                    self.s.catalogue_url,
                ],
            )
            self.store.add_event(
                lead_id,
                "auto_reply",
                "tpl:" + leadgen_id,
                self.clock(),
                channel="whatsapp_template",
                actor="bot",
                meta={"ok": res.ok, "error": res.error},
            )
            if res.ok:
                self.store.update_lead(lead_id, first_auto_reply_at=iso(self.clock()))
        self.alert(self.lead(lead_id), "call_now", "notify:leadgen:" + leadgen_id, now)
        return "alerted"

    def handle_form(
        self,
        phone_raw: str,
        name: str | None,
        message: str,
        consent: bool,
        source: str = "website",
        detail: str | None = None,
        submission_id: str | None = None,
    ) -> tuple[str, str]:
        phone = normalise(phone_raw)
        if not phone:
            raise ValueError("invalid phone")
        now = self.clock()
        lead_id, _ = self.store.upsert_lead(
            phone, source, now, name=name or None, source_detail=detail, synthetic=self.s.synthetic_mode
        )
        sid = submission_id or uuid.uuid4().hex
        if self.store.add_event(lead_id, "inbound", "form:" + sid, now, channel=source, body=message):
            if consent and not self.lead(lead_id).get("consent_source"):
                self.store.update_lead(lead_id, consent_source="website_form_checkbox", consent_at=iso(now))
            self.process(lead_id)
            self.alert(self.lead(lead_id), "call_now", "notify:form:" + sid, now)
        return lead_id, self.wa_me_link(f"#{lead_id[:6]} (ref:web)")

    def handle_manual(
        self,
        phone_raw: str,
        name: str | None,
        source: str,
        notes: str,
        consent: bool,
        responded: bool,
        actor: str,
        fields: dict[str, str] | None = None,
    ) -> str:
        phone = normalise(phone_raw)
        if not phone:
            raise ValueError("invalid phone")
        now = self.clock()
        lead_id, _ = self.store.upsert_lead(
            phone, source, now, name=name or None, synthetic=self.s.synthetic_mode
        )
        self.store.add_event(
            lead_id, "inbound", "manual:" + uuid.uuid4().hex, now, channel=source, actor=actor, body=notes
        )
        upd: dict[str, Any] = {k: v for k, v in (fields or {}).items() if v}
        if consent and not self.lead(lead_id).get("consent_source"):
            upd.update(consent_source="staff_recorded_verbal", consent_at=iso(now))
        if upd:
            self.store.update_lead(lead_id, **upd)
        self.process(lead_id)
        if responded:
            self.human_action(lead_id, "replied", actor, channel="in_person")
        return lead_id

    # -- humans ----------------------------------------------------------------------------
    def human_action(
        self,
        lead_id: str,
        action: str,
        actor: str,
        value: int | None = None,
        text: str | None = None,
        channel: str = "phone",
    ) -> str:
        now = self.clock()
        lead = self.lead(lead_id)
        key = f"{action}:{lead_id}:{uuid.uuid4().hex}"
        if action == "send":
            if not text:
                return "empty"
            res = self.send_session(lead, text, "human_reply", key, now, actor=actor)
            if res is None or not res.ok:
                return "not_sent_window_closed_or_error"
            action = "replied_wa"
        elif action == "replied":
            self.store.add_event(lead_id, "human_reply", key, now, channel=channel, actor=actor)
        elif action == "quote":
            self.store.add_event(lead_id, "quote", key, now, actor=actor, meta={"value": value})
            self.store.update_lead(lead_id, quote_value=value, status="quoted")
        elif action == "won":
            self.store.add_event(lead_id, "won", key, now, actor=actor, meta={"value": value})
            self.store.update_lead(lead_id, invoice_value=value, status="won")
        elif action == "lost":
            self.store.add_event(lead_id, "lost", key, now, actor=actor, body=text)
            self.store.update_lead(lead_id, lost_reason=text, status="lost")
        else:
            raise ValueError(f"unknown action {action}")
        lead = self.lead(lead_id)
        if action in ("replied", "replied_wa", "quote", "won") and not lead.get("first_human_reply_at"):
            self.store.update_lead(lead_id, first_human_reply_at=iso(now))
        if lead.get("status") == "new":
            self.store.update_lead(lead_id, status="contacted")
        return action
