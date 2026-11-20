from __future__ import annotations

import json
from datetime import datetime, timedelta

from speed_to_lead import dashboard, metrics, sla
from speed_to_lead.app import status_line
from speed_to_lead.db import Store

from .conftest import IST, Env

PHONE = "+919812345678"
WA = PHONE.lstrip("+")


def test_verify_handshake(env: Env) -> None:
    ok = env.client.get(
        "/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"}
    )
    assert ok.status_code == 200 and ok.text == "42"
    bad = env.client.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "no"})
    assert bad.status_code == 403
    assert (
        env.client.post(
            "/webhooks/meta", content=b"{}", headers={"X-Hub-Signature-256": "sha256=0"}
        ).status_code
        == 403
    )


def test_inbound_auto_reply_dedupe_and_enrichment(env: Env) -> None:
    assert env.wa(WA, "seepage problem in Undri 2BHK, rate?", "w1") == 200
    assert len(env.sender.to(PHONE)) == 1
    lead = env.store.get_lead_by_phone(PHONE)
    assert lead and lead["project_type"] == "waterproofing" and lead["owner"] == "painter"
    assert lead["first_auto_reply_at"] and lead["consent_source"] == "customer_initiated_whatsapp"
    assert "few minutes" in env.sender.to(PHONE)[0]
    env.wa(WA, "seepage problem in Undri 2BHK, rate?", "w1")  # Meta redelivery
    env.wa(WA, "next week", "w2")  # conversation continues: no second auto reply
    assert len(env.sender.to(PHONE)) == 1
    assert env.store.get_lead_by_phone(PHONE)["timeline"] == "soon"  # type: ignore[index]
    auto = [e for e in env.store.events(lead["id"]) if e["kind"] == "auto_reply"]
    assert "pipeline_ms" in json.loads(auto[0]["meta"])


def test_out_of_hours_and_stop_start(env: Env) -> None:
    env.clock.dt = datetime(2026, 11, 17, 22, 0, tzinfo=IST)
    env.wa(WA, "namaste, paint chahiye", "n1")
    assert "tomorrow" in env.sender.to(PHONE)[0] or "कल" in env.sender.to(PHONE)[0]
    env.wa(WA, "STOP", "n2")
    lead = env.store.get_lead_by_phone(PHONE)
    assert lead and lead["opted_out"] == 1 and len(env.sender.to(PHONE)) == 2
    env.wa(WA, "any update?", "n3")
    assert len(env.sender.to(PHONE)) == 2
    env.wa(WA, "START", "n4")
    assert env.store.get_lead_by_phone(PHONE)["opted_out"] == 0  # type: ignore[index]


def test_owner_ping_is_not_a_lead(env: Env) -> None:
    env.wa("919000000100", "hi", "o1")
    assert env.store.leads() == [] and env.store.owner_last_ping("father") is not None


def test_ctwa_attribution_and_cap(env: Env) -> None:
    env.wa(WA, "saw your ad", "c1", referral={"source_id": "AD9"})
    lead = env.store.get_lead_by_phone(PHONE)
    assert lead and lead["source"] == "ctwa_ad" and lead["source_detail"] == "AD9"
    env.settings.service_msg_monthly_cap = 1
    env.wa("919812345679", "hello", "c2")
    assert env.sender.to("+919812345679") == []


def test_leadgen_alerts_and_paid_template_off(env: Env) -> None:
    env.leads["LG1"] = {
        "platform": "ig",
        "form_id": "F",
        "field_data": [
            {"name": "full_name", "values": ["Asha"]},
            {"name": "phone_number", "values": ["98123 45678"]},
            {"name": "what_work", "values": ["exterior row house"]},
            {"name": "whatsapp_opt_in", "values": ["Yes"]},
        ],
    }
    raw = json.dumps(
        {"object": "page", "entry": [{"changes": [{"field": "leadgen", "value": {"leadgen_id": "LG1"}}]}]}
    )
    from speed_to_lead.whatsapp import sign

    for _ in range(2):
        env.client.post(
            "/webhooks/meta", content=raw, headers={"X-Hub-Signature-256": sign("test-secret", raw.encode())}
        )
    lead = env.store.get_lead_by_phone(PHONE)
    assert lead and lead["source"] == "meta_lead_ad" and lead["consent_source"] == "meta_lead_form_optin"
    assert env.sender.templates == [] and env.sender.sent == []
    alerts = [e for e in env.store.events(lead["id"]) if e["kind"] == "alert"]
    assert len(alerts) == 1 and alerts[0]["body"] == "call_now"
    env.settings.allow_paid_templates = True
    env.leads["LG2"] = {
        **env.leads["LG1"],
        "field_data": [
            {"name": "phone_number", "values": ["9812345670"]},
            {"name": "whatsapp_opt_in", "values": ["yes"]},
        ],
    }
    env.pipeline.handle_leadgen({"leadgen_id": "LG2"})
    assert env.sender.templates == [("+919812345670", "ut_enquiry_received")]


def test_form_endpoint(env: Env) -> None:
    assert env.client.post("/webhooks/form", json={"phone": "98123 45678"}).status_code == 422
    assert env.client.post("/webhooks/form", json={"phone": "1", "consent": True}).status_code == 422
    r = env.client.post(
        "/webhooks/form", data={"phone": "98123 45678", "message": "wood polish", "consent": "on"}
    )
    assert r.json()["whatsapp_link"].startswith("https://wa.me/910000000000?text=")
    env.client.post("/webhooks/form", json={"phone": "9812345670", "consent": True, "website": "bot"})
    assert env.store.get_lead_by_phone("+919812345670") is None
    assert env.store.get_lead_by_phone(PHONE)["consent_source"] == "website_form_checkbox"  # type: ignore[index]


def test_staff_auth_manual_and_funnel(env: Env) -> None:
    assert env.client.get("/staff").status_code == 401
    assert env.client.get("/staff", auth=("staff", "bad")).status_code == 401
    r = env.client.post(
        "/staff/new",
        auth=("staff", "pw"),
        data={"phone": "98123 45678", "source": "walk_in", "notes": "3BHK interior", "responded": "1"},
    )
    assert "Saved" in r.text
    lead = env.store.get_lead_by_phone(PHONE)
    assert lead and lead["first_human_reply_at"] and lead["status"] == "contacted"
    assert env.client.get(f"/staff/lead/{lead['id']}", auth=("staff", "pw")).status_code == 200
    for action, value in (("quote", "25,000"), ("won", "₹24000")):
        env.client.post(
            f"/staff/lead/{lead['id']}/action", auth=("staff", "pw"), data={"action": action, "value": value}
        )
    lead = env.store.get_lead_by_phone(PHONE)
    assert lead and (lead["status"], lead["quote_value"], lead["invoice_value"]) == ("won", 25000, 24000)
    assert "Walk-in" in env.client.get("/staff/new", auth=("staff", "pw")).text


def test_staff_send_requires_window(env: Env) -> None:
    env.wa(WA, "hi", "s1")
    lead = env.store.get_lead_by_phone(PHONE)
    assert lead
    assert env.pipeline.human_action(lead["id"], "send", "papa", text="Rate is 300/L") == "replied_wa"
    env.clock.advance(hours=25)
    assert (
        env.pipeline.human_action(lead["id"], "send", "papa", text="hello?")
        == "not_sent_window_closed_or_error"
    )


def test_sla_and_followups(env: Env) -> None:
    env.wa(WA, "need paint", "a1")
    lead = env.store.get_lead_by_phone(PHONE)
    assert lead
    p, t0 = env.pipeline, env.clock.dt
    assert sla.tick(p, t0 + timedelta(minutes=4)) == []
    assert sla.tick(p, t0 + timedelta(minutes=6)) == [f"sla1:{lead['id']}"]
    assert sla.tick(p, t0 + timedelta(minutes=7)) == []
    assert sla.tick(p, t0 + timedelta(minutes=16)) == [
        f"sla2:{lead['id']}->father"
    ]  # owner hussain -> father
    acts = sla.tick(p, t0 + timedelta(hours=2, minutes=1))
    assert acts == [f"fu:{lead['id']}:1"] and len(env.sender.to(PHONE)) == 2
    acts = sla.tick(p, t0 + timedelta(hours=25))
    assert acts == [f"skip:fu:{lead['id']}:2"]  # window closed -> no paid message, call instead


def test_sla_waits_for_opening(env: Env) -> None:
    env.clock.dt = datetime(2026, 11, 17, 23, 0, tzinfo=IST)
    env.wa(WA, "hello", "q1")
    assert sla.tick(env.pipeline, datetime(2026, 11, 17, 23, 30, tzinfo=IST)) == []
    assert sla.tick(env.pipeline, datetime(2026, 11, 18, 9, 36, tzinfo=IST))[0].startswith("sla1")


def test_cron_endpoint(env: Env) -> None:
    assert env.client.post("/cron/tick").status_code == 403
    assert env.client.post("/cron/tick", headers={"X-Cron-Secret": "cs"}).json() == {"actions": []}


def test_metrics_dashboard_and_separation(env: Env) -> None:
    env.wa(WA, "Hi I am Ravi, need paint", "m1", name="Ravi Kumar")
    env.clock.advance(minutes=3)
    lead = env.store.get_lead_by_phone(PHONE)
    assert lead
    env.pipeline.human_action(lead["id"], "won", "papa", 5000)
    env.store.add_baseline(
        "walk_in",
        datetime(2026, 11, 1, 10, 0, tzinfo=IST),
        datetime(2026, 11, 1, 10, 20, tzinfo=IST),
        "won",
        None,
        7000,
        None,
        None,
        env.clock(),
    )
    env.store.add_baseline(
        "walk_in",
        datetime(2026, 11, 2, 10, 0, tzinfo=IST),
        None,
        "lost",
        None,
        None,
        None,
        None,
        env.clock(),
        synthetic=True,
    )
    m = metrics.compute(env.store, env.settings)
    assert m["leads_total"] == 1 and m["pct_auto_within_60s"] == 100.0
    assert m["human_first_response_min"]["median"] == 3.0 and m["funnel"]["revenue"] == 5000
    assert m["before_after"]["baseline"]["leads"] == 1  # synthetic baseline row excluded
    assert metrics.compute(env.store, env.settings, synthetic=True)["leads_total"] == 0
    html = dashboard.render(m, status_line(m), "now")
    assert "Ravi" not in html and "98123" not in html and "SYNTHETIC DEMO DATA" not in html
    assert env.client.get("/dashboard").status_code == 200
    assert metrics.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == 9
    assert metrics.percentile([], 50) is None


def test_baseline_pages(env: Env) -> None:
    r = env.client.post(
        "/staff/baseline",
        auth=("staff", "pw"),
        data={
            "source": "whatsapp",
            "lead_at": "2026-11-10T11:00",
            "first_reply_at": "2026-11-10T11:40",
            "outcome": "quoted",
        },
    )
    assert "Saved" in r.text
    csv_text = env.client.get("/staff/baseline.csv", auth=("staff", "pw")).text
    assert "whatsapp" in csv_text and "2026-11-10T05:30" in csv_text


def test_status_line_week0_and_migrate_idempotent_and_forget() -> None:
    s = Store("sqlite:///:memory:")
    assert s.migrate() and s.migrate() == []
    from speed_to_lead.config import Settings

    m = metrics.compute(s, Settings())
    assert status_line(m).startswith("Week 0")
    lid, created = s.upsert_lead(PHONE, "walk_in", datetime.now(IST), name="X")
    assert created and s.upsert_lead(PHONE, "website", datetime.now(IST)) == (lid, False)
    assert s.forget(PHONE) and s.get_lead_by_phone(PHONE) is None
