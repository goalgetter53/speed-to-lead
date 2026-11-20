"""Store round-trip on real Postgres when STL_TEST_POSTGRES_URL is set (CI service container)."""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from speed_to_lead.db import Store

from .conftest import IST

URL = os.environ.get("STL_TEST_POSTGRES_URL", "")


@pytest.mark.skipif(not URL, reason="STL_TEST_POSTGRES_URL not set")
def test_postgres_store_roundtrip() -> None:
    s = Store(URL)
    for t in ("events", "baseline_log", "owner_pings", "leads", "schema_migrations"):
        s.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    assert s.migrate() == ["001_init.sql", "002_rls.postgres.sql"]
    assert s.migrate() == []
    now = datetime(2026, 11, 17, 11, 0, tzinfo=IST)
    lid, created = s.upsert_lead("+919812345678", "walk_in", now, name="A")
    assert created and s.upsert_lead("+919812345678", "website", now) == (lid, False)
    assert s.add_event(lid, "inbound", "k1", now, body="hi") and not s.add_event(lid, "inbound", "k1", now)
    s.update_lead(lid, score=50, distance_km=2.5)
    row = s.get_lead(lid)
    assert row and row["score"] == 50 and row["distance_km"] == 2.5
    s.owner_ping("father", now)
    s.owner_ping("father", now)
    assert s.owner_last_ping("father") == now
    s.add_baseline("walk_in", now, None, "open", None, None, None, None, now)
    assert len(s.baseline()) == 1 and s.count_events_since(("inbound",), now) == 1
