"""Command line: serve | migrate | tick | dashboard | baseline-import | forget | demo."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Settings
from .db import Store, iso


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stl", description="WhatsApp-first speed-to-lead for United Trader")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8000)
    sub.add_parser("migrate")
    sub.add_parser("tick", help="run SLA + follow-up checks once")
    d = sub.add_parser("dashboard", help="write the anonymised static dashboard from REAL data")
    d.add_argument("--out", default="site/index.html")
    d.add_argument("--json", default="site/metrics.json")
    b = sub.add_parser(
        "baseline-import", help="import the paper logbook CSV (docs/baseline_logbook.csv format)"
    )
    b.add_argument("csv")
    f = sub.add_parser("forget", help="DPDP erasure request: anonymise one customer")
    f.add_argument("phone")
    sub.add_parser("demo")
    a = ap.parse_args(argv)
    s = Settings.from_env()

    if a.cmd == "demo":
        from .demo import run

        return run()
    if a.cmd == "serve":
        import uvicorn

        from .app import create_app

        uvicorn.run(create_app(s), host=a.host, port=a.port)
        return 0
    store = Store(s.database_url)
    applied = store.migrate()
    if a.cmd == "migrate":
        print("applied:", applied or "nothing (up to date)")
    elif a.cmd == "tick":
        from .app import create_app
        from .sla import tick

        app = create_app(s, store=store)
        print(json.dumps(tick(app.state.pipeline, datetime.now(UTC))))
    elif a.cmd == "dashboard":
        from . import dashboard, metrics
        from .app import status_line

        m = metrics.compute(store, s, synthetic=False)
        now = iso(datetime.now(UTC))
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(dashboard.render(m, status_line(m), now), encoding="utf-8")
        Path(a.json).write_text(json.dumps({"generated_at": now, **m}, indent=2, default=str))
        print(
            f"{status_line(m)}\nleads={m['leads_total']} "
            f"baseline_entries={m['before_after']['baseline']['leads']}"
            f" -> {a.out}"
        )
    elif a.cmd == "baseline-import":
        tz = ZoneInfo(s.timezone)
        n = 0
        with open(a.csv, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if not r.get("lead_at"):
                    continue
                lead_at = datetime.fromisoformat(r["lead_at"]).replace(tzinfo=tz)
                rep = (
                    datetime.fromisoformat(r["first_reply_at"]).replace(tzinfo=tz)
                    if r.get("first_reply_at")
                    else None
                )
                store.add_baseline(
                    r.get("source") or "other",
                    lead_at,
                    rep,
                    r.get("outcome") or "open",
                    int(r["quote_value"]) if r.get("quote_value") else None,
                    int(r["invoice_value"]) if r.get("invoice_value") else None,
                    r.get("notes") or None,
                    r.get("logged_by") or None,
                    datetime.now(UTC),
                )
                n += 1
        print(f"imported {n} baseline rows")
    elif a.cmd == "forget":
        from .phone import normalise

        ok = store.forget(normalise(a.phone) or a.phone)
        print("erased" if ok else "not found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
