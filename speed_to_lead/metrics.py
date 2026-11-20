"""Speed-to-lead metrics from the lead store. Aggregates only: no names or phone numbers leave here.

Real and synthetic data are never mixed: `compute(store, synthetic=False)` reads only real rows.
Percentiles use the nearest-rank method. Human response times are measured from the moment the
shop was open (an 11 pm enquiry answered at 9:35 am counts as 5 min), for both baseline and live.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any

from . import hours
from .config import Settings
from .db import Row, Store, parse_iso


def percentile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = max(1, math.ceil(q / 100 * len(s)))
    return s[k - 1]


def dist(xs: list[float]) -> dict[str, Any]:
    return {
        "n": len(xs),
        "median": percentile(xs, 50),
        "p90": percentile(xs, 90),
        "max": max(xs) if xs else None,
    }


def _share(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def human_minutes(lead_at: datetime, reply_at: datetime, s: Settings) -> float:
    start = hours.sla_start(lead_at, s)
    return max(0.0, (reply_at - start).total_seconds() / 60)


def compute(store: Store, s: Settings, synthetic: bool = False) -> dict[str, Any]:
    flag = 1 if synthetic else 0
    leads = [r for r in store.leads() if int(r["synthetic"]) == flag]
    first_channel = {
        r["lead_id"]: r["channel"]
        for r in store.query(
            "SELECT lead_id, channel, at FROM events WHERE kind = 'inbound' ORDER BY at DESC"
        )
    }
    auto_secs: list[float] = []
    wa_leads = 0
    human_mins: list[float] = []
    by_source: dict[str, dict[str, int]] = defaultdict(
        lambda: {"leads": 0, "contacted": 0, "quoted": 0, "won": 0, "revenue": 0}
    )
    for r in leads:
        created = parse_iso(str(r["created_at"]))
        if first_channel.get(r["id"]) == "whatsapp":
            wa_leads += 1
            if r["first_auto_reply_at"]:
                auto_secs.append((parse_iso(str(r["first_auto_reply_at"])) - created).total_seconds())
        if r["first_human_reply_at"]:
            human_mins.append(human_minutes(created, parse_iso(str(r["first_human_reply_at"])), s))
        b = by_source[str(r["source"])]
        b["leads"] += 1
        b["contacted"] += 1 if r["first_human_reply_at"] else 0
        b["quoted"] += 1 if r["quote_value"] is not None or r["status"] in ("quoted", "won") else 0
        b["won"] += 1 if r["status"] == "won" else 0
        b["revenue"] += int(r["invoice_value"] or 0) if r["status"] == "won" else 0
    funnel = {
        k: sum(b[k] for b in by_source.values()) for k in ("leads", "contacted", "quoted", "won", "revenue")
    }
    live = {
        "leads": len(leads),
        "human_first_response_min": dist(human_mins),
        "pct_human_within_5min": _share(sum(m <= 5 for m in human_mins), len(human_mins)),
        "conversion_pct": _share(funnel["won"], funnel["leads"]),
        "revenue": funnel["revenue"],
    }
    return {
        "synthetic": synthetic,
        "leads_total": len(leads),
        "auto_first_response_sec": dist(auto_secs),
        "pct_auto_within_60s": _share(sum(x <= 60 for x in auto_secs), wa_leads),
        "whatsapp_leads": wa_leads,
        "human_first_response_min": live["human_first_response_min"],
        "pct_human_within_5min": live["pct_human_within_5min"],
        "by_source": dict(sorted(by_source.items(), key=lambda kv: -kv[1]["leads"])),
        "funnel": funnel,
        "before_after": {"baseline": baseline_summary(store.baseline(), s, flag), "live": live},
    }


def baseline_summary(rows: list[Row], s: Settings, flag: int) -> dict[str, Any]:
    rows = [r for r in rows if int(r["synthetic"]) == flag]
    mins = [
        human_minutes(parse_iso(str(r["lead_at"])), parse_iso(str(r["first_reply_at"])), s)
        for r in rows
        if r["first_reply_at"]
    ]
    won = [r for r in rows if r["outcome"] == "won"]
    days = sorted({str(r["lead_at"])[:10] for r in rows})
    return {
        "leads": len(rows),
        "days_logged": len(days),
        "never_replied": sum(1 for r in rows if not r["first_reply_at"]),
        "human_first_response_min": dist(mins),
        "pct_human_within_5min": _share(sum(m <= 5 for m in mins), len(mins)),
        "conversion_pct": _share(len(won), len(rows)),
        "revenue": sum(int(r["invoice_value"] or 0) for r in won),
    }
