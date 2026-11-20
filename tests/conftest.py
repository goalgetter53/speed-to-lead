from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from speed_to_lead.app import create_app
from speed_to_lead.config import Settings
from speed_to_lead.db import Store
from speed_to_lead.pipeline import Pipeline
from speed_to_lead.whatsapp import SendResult, sign

IST = ZoneInfo("Asia/Kolkata")
SECRET = "test-secret"
PG_URL = os.environ.get("STL_TEST_POSTGRES_URL", "")  # set in CI to run every test on Postgres


@dataclass
class FakeSender:
    sent: list[tuple[str, str]] = field(default_factory=list)
    templates: list[tuple[str, str]] = field(default_factory=list)

    def send_text(self, to_e164: str, body: str) -> SendResult:
        self.sent.append((to_e164, body))
        return SendResult(ok=True, message_id=f"wamid.T{len(self.sent)}")

    def send_template(self, to_e164: str, name: str, lang: str, params: list[str]) -> SendResult:
        self.templates.append((to_e164, name))
        return SendResult(ok=True, message_id="wamid.TPL")

    def to(self, e164: str) -> list[str]:
        return [b for t, b in self.sent if t == e164]


class Clock:
    def __init__(self, dt: datetime) -> None:
        self.dt = dt

    def __call__(self) -> datetime:
        return self.dt

    def advance(self, **kw: float) -> None:
        self.dt = self.dt + timedelta(**kw)


@dataclass
class Env:
    client: TestClient
    pipeline: Pipeline
    sender: FakeSender
    clock: Clock
    settings: Settings
    leads: dict[str, dict[str, Any]]

    @property
    def store(self) -> Store:
        return self.pipeline.store

    def wa(
        self, wa_id: str, text: str, wamid: str, name: str = "Test", referral: dict[str, Any] | None = None
    ) -> int:
        msg: dict[str, Any] = {
            "from": wa_id,
            "id": wamid,
            "timestamp": str(int(self.clock().timestamp())),
            "type": "text",
            "text": {"body": text},
        }
        if referral:
            msg["referral"] = referral
        raw = json.dumps(
            {
                "object": "whatsapp_business_account",
                "entry": [
                    {
                        "changes": [
                            {
                                "field": "messages",
                                "value": {
                                    "contacts": [{"wa_id": wa_id, "profile": {"name": name}}],
                                    "messages": [msg],
                                },
                            }
                        ]
                    }
                ],
            }
        ).encode()
        r = self.client.post(
            "/webhooks/meta", content=raw, headers={"X-Hub-Signature-256": sign(SECRET, raw)}
        )
        return int(r.status_code)


def make_settings(**kw: Any) -> Settings:
    base: dict[str, Any] = dict(
        database_url="sqlite:///:memory:",
        wa_app_secret=SECRET,
        wa_verify_token="vt",
        staff_password="pw",
        sla_loop_seconds=0,
        cron_secret="cs",
        catalogue_url="https://example.com/cat",
        wa_business_number="910000000000",
        telegram_bot_token="",
        owner_father_wa="+919000000100",
    )
    base.update(kw)
    return Settings(**base)


@pytest.fixture
def env() -> Iterator[Env]:
    s = make_settings()
    sender = FakeSender()
    clock = Clock(datetime(2026, 11, 17, 11, 0, tzinfo=IST))
    leads: dict[str, dict[str, Any]] = {}
    if PG_URL:
        reset = Store(PG_URL)
        for t in ("events", "baseline_log", "owner_pings", "leads", "schema_migrations"):
            reset.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    app = create_app(s, wa=sender, clock=clock, leadgen=lambda lid: leads[lid])
    with TestClient(app) as c:
        yield Env(c, app.state.pipeline, sender, clock, s, leads)
