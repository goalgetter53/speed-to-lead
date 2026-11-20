"""SLA timers (human reply within 5 min of shop-open time), escalation, and free follow-ups.

Run `tick()` every ~30 s: in-process loop, or POST /cron/tick from a free external cron when the host sleeps.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from . import hours, messages
from .db import parse_iso
from .pipeline import Pipeline

STALE = timedelta(hours=48)


def tick(p: Pipeline, now: datetime) -> list[str]:
    s, store = p.s, p.store
    done: list[str] = []
    rows = store.query(
        "SELECT * FROM leads WHERE first_human_reply_at IS NULL AND opted_out = 0 AND status = 'new'"
    )
    for lead in rows:
        base = parse_iso(str(lead["created_at"]))  # first unanswered enquiry
        if now - base > STALE:
            continue
        start = hours.sla_start(base, s)
        lid = str(lead["id"])
        if now >= start + timedelta(minutes=s.sla_human_minutes) and p.alert(
            lead, "sla1", f"alert:{lid}:1", now
        ):
            done.append(f"sla1:{lid}")
        if now >= start + timedelta(minutes=s.sla_escalate_minutes):
            target = "father" if lead.get("owner") == "hussain" else "hussain"
            if p.alert(lead, "sla2", f"alert:{lid}:2", now, owner=target):
                done.append(f"sla2:{lid}->{target}")
    # Follow-ups: only inside the free 24h window, only during shop hours, only if the customer went quiet
    # after our auto-reply and no human has taken over.
    rows = store.query(
        "SELECT * FROM leads WHERE first_auto_reply_at IS NOT NULL AND opted_out = 0 "
        "AND first_human_reply_at IS NULL AND status = 'new'"
    )
    for lead in rows:
        auto_at = parse_iso(str(lead["first_auto_reply_at"]))
        if lead.get("last_inbound_at") and parse_iso(str(lead["last_inbound_at"])) > auto_at:
            continue
        lid = str(lead["id"])
        for i, h in enumerate(s.followups(), 1):
            key = f"fu:{lid}:{i}"
            if now < auto_at + timedelta(hours=h) or store.has_event(key) or store.has_event(key + ":skip"):
                continue
            if not p.window_open(lead, now):
                store.add_event(
                    lid, "note", key + ":skip", now, body="window closed; call the customer instead"
                )
                done.append(f"skip:{key}")
                continue
            if not hours.is_open(now, s):
                continue  # quiet hours: try again at the next tick while the window is still open
            body = messages.followup(str(lead.get("language") or "en"), i, s.catalogue_url)
            if p.send_session(lead, body, "followup", key, now):
                done.append(key)
    return done
