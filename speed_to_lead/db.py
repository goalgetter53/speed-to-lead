"""Lead store over SQLite (local) or Postgres/Supabase (production). Plain SQL, `?` placeholders."""

from __future__ import annotations

import importlib
import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

Row = dict[str, Any]
MIGRATIONS = Path(__file__).parent / "migrations"

LEAD_FIELDS = {
    "name",
    "source",
    "source_detail",
    "last_inbound_at",
    "language",
    "area",
    "pincode",
    "distance_km",
    "project_type",
    "size_text",
    "budget_text",
    "timeline",
    "customer_type",
    "score",
    "score_bucket",
    "score_explain",
    "owner",
    "route_reason",
    "status",
    "consent_source",
    "consent_at",
    "opted_out",
    "opted_out_at",
    "first_auto_reply_at",
    "first_human_reply_at",
    "quote_value",
    "invoice_value",
    "lost_reason",
}


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def new_id() -> str:
    return uuid.uuid4().hex


class Store:
    def __init__(self, database_url: str) -> None:
        self._lock = threading.RLock()
        self.dialect = "postgres" if database_url.startswith(("postgres://", "postgresql://")) else "sqlite"
        self._conn: Any
        if self.dialect == "postgres":
            psycopg: Any = importlib.import_module("psycopg")
            self._conn = psycopg.connect(database_url, autocommit=True)
        else:
            path = database_url.removeprefix("sqlite:///")
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")

    # -- low level -------------------------------------------------------------------------
    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.dialect == "postgres" else sql

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(self._sql(sql), params)
            return int(cur.rowcount)

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[Row]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(self._sql(sql), params)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            return [dict(zip(cols, tuple(r), strict=True)) for r in rows]

    def migrate(self) -> list[str]:
        self.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        done = {r["version"] for r in self.query("SELECT version FROM schema_migrations")}
        applied = []
        for f in sorted(MIGRATIONS.glob("*.sql")):
            parts = f.name.split(".")
            if len(parts) == 3 and parts[1] != self.dialect:
                continue
            if f.name in done:
                continue
            for stmt in f.read_text().split(";"):
                body = "\n".join(ln for ln in stmt.splitlines() if not ln.strip().startswith("--")).strip()
                if body:
                    self.execute(body)
            self.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (f.name, iso(datetime.now(UTC))),
            )
            applied.append(f.name)
        return applied

    # -- leads -----------------------------------------------------------------------------
    def upsert_lead(
        self,
        phone: str,
        source: str,
        now: datetime,
        name: str | None = None,
        source_detail: str | None = None,
        synthetic: bool = False,
    ) -> tuple[str, bool]:
        """Dedupe by phone. Returns (lead_id, created). First-touch source is kept."""
        lid = new_id()
        n = self.execute(
            "INSERT INTO leads (id, phone, name, source, source_detail, created_at, synthetic) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(phone) DO NOTHING",
            (lid, phone, name, source, source_detail, iso(now), int(synthetic)),
        )
        if n == 1:
            return lid, True
        row = self.query("SELECT id, name FROM leads WHERE phone = ?", (phone,))[0]
        if name and not row["name"]:
            self.update_lead(row["id"], name=name)
        return str(row["id"]), False

    def update_lead(self, lead_id: str, **fields: Any) -> None:
        bad = set(fields) - LEAD_FIELDS
        if bad:
            raise ValueError(f"unknown lead fields: {bad}")
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.execute(f"UPDATE leads SET {cols} WHERE id = ?", (*fields.values(), lead_id))

    def get_lead(self, lead_id: str) -> Row | None:
        rows = self.query("SELECT * FROM leads WHERE id = ?", (lead_id,))
        return rows[0] if rows else None

    def get_lead_by_phone(self, phone: str) -> Row | None:
        rows = self.query("SELECT * FROM leads WHERE phone = ?", (phone,))
        return rows[0] if rows else None

    def leads(self, include_synthetic: bool = True) -> list[Row]:
        where = "" if include_synthetic else " WHERE synthetic = 0"
        return self.query("SELECT * FROM leads" + where + " ORDER BY created_at DESC")

    def forget(self, phone: str) -> bool:
        """DPDP erasure: anonymise personal data, keep aggregate counts."""
        lead = self.get_lead_by_phone(phone)
        if not lead:
            return False
        self.execute(
            "UPDATE leads SET phone = ?, name = NULL, area = NULL, pincode = NULL WHERE id = ?",
            ("erased:" + lead["id"], lead["id"]),
        )
        self.execute("UPDATE events SET body = NULL, meta = NULL WHERE lead_id = ?", (lead["id"],))
        return True

    # -- events ----------------------------------------------------------------------------
    def add_event(
        self,
        lead_id: str,
        kind: str,
        event_key: str,
        at: datetime,
        channel: str | None = None,
        actor: str | None = None,
        body: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> bool:
        n = self.execute(
            "INSERT INTO events (id, lead_id, event_key, kind, channel, actor, body, meta, at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(event_key) DO NOTHING",
            (
                new_id(),
                lead_id,
                event_key,
                kind,
                channel,
                actor,
                body,
                json.dumps(meta) if meta else None,
                iso(at),
            ),
        )
        return n == 1

    def events(self, lead_id: str) -> list[Row]:
        return self.query("SELECT * FROM events WHERE lead_id = ? ORDER BY at", (lead_id,))

    def has_event(self, event_key: str) -> bool:
        return bool(self.query("SELECT 1 AS x FROM events WHERE event_key = ?", (event_key,)))

    def count_events_since(self, kinds: tuple[str, ...], since: datetime) -> int:
        marks = ",".join("?" for _ in kinds)
        rows = self.query(
            f"SELECT COUNT(*) AS n FROM events WHERE kind IN ({marks}) AND at >= ?", (*kinds, iso(since))
        )
        return int(rows[0]["n"])

    # -- owners ----------------------------------------------------------------------------
    def owner_ping(self, owner: str, at: datetime) -> None:
        self.execute(
            "INSERT INTO owner_pings (owner, last_at) VALUES (?, ?) "
            "ON CONFLICT(owner) DO UPDATE SET last_at = excluded.last_at",
            (owner, iso(at)),
        )

    def owner_last_ping(self, owner: str) -> datetime | None:
        rows = self.query("SELECT last_at FROM owner_pings WHERE owner = ?", (owner,))
        return parse_iso(rows[0]["last_at"]) if rows else None

    # -- baseline --------------------------------------------------------------------------
    def add_baseline(
        self,
        source: str,
        lead_at: datetime,
        first_reply_at: datetime | None,
        outcome: str,
        quote_value: int | None,
        invoice_value: int | None,
        notes: str | None,
        logged_by: str | None,
        now: datetime,
        synthetic: bool = False,
    ) -> str:
        bid = new_id()
        self.execute(
            "INSERT INTO baseline_log (id, source, lead_at, first_reply_at, outcome, quote_value, "
            "invoice_value, "
            "notes, logged_by, synthetic, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                bid,
                source,
                iso(lead_at),
                iso(first_reply_at) if first_reply_at else None,
                outcome,
                quote_value,
                invoice_value,
                notes,
                logged_by,
                int(synthetic),
                iso(now),
            ),
        )
        return bid

    def baseline(self, include_synthetic: bool = True) -> list[Row]:
        where = "" if include_synthetic else " WHERE synthetic = 0"
        return self.query("SELECT * FROM baseline_log" + where + " ORDER BY lead_at")
