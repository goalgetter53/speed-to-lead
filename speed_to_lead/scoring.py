"""Transparent lead score (0-100) with one explanation line per rule that fired.

Weights are starting guesses, not fitted. After ~4 weeks of won/lost outcomes, re-tune them against
`stl metrics` (conversion by bucket). Keep them in this one table so changes are reviewable.
"""

from __future__ import annotations

from typing import Any

from .enrich import Enrichment

W = {
    "base": 10,
    "project_known": 10,
    "waterproofing": 10,  # leak problems are urgent and high-ticket (material + application)
    "size_known": 8,
    "big_home": 10,
    "budget_known": 7,
    "timeline_now": 20,
    "timeline_soon": 10,
    "timeline_later": -5,
    "near_5km": 15,
    "near_10km": 8,
    "far_20km": -10,
    "contractor": 15,  # repeat trade volume
    "price_intent": 5,
    "brand_named": 5,
    "high_intent_source": 5,  # walk-in, phone call, click-to-WhatsApp ad
}
HIGH_INTENT_SOURCES = {"walk_in", "phone_call", "ctwa_ad", "gbp_call"}
HOT, WARM = 60, 35


def score(lead: dict[str, Any], e: Enrichment) -> tuple[int, str, list[str]]:
    lines: list[str] = []
    total = 0

    def add(key: str, why: str) -> None:
        nonlocal total
        total += W[key]
        lines.append(f"{W[key]:+d} {why}")

    add("base", "new enquiry")
    project = lead.get("project_type") or e.project_type
    if project:
        add("project_known", f"project type known: {project}")
        if project == "waterproofing":
            add("waterproofing", "waterproofing / seepage problem (urgent, high value)")
    if lead.get("size_text") or e.size_text:
        add("size_known", f"size given: {lead.get('size_text') or e.size_text}")
    if e.big_home:
        add("big_home", "large job (3BHK+ / bungalow / >=1200 sq ft / society)")
    if lead.get("budget_text") or e.budget_text:
        add("budget_known", f"budget mentioned: {lead.get('budget_text') or e.budget_text}")
    tl = lead.get("timeline") or e.timeline
    if tl in ("now", "soon", "later"):
        add(f"timeline_{tl}", f"timeline: {tl} ('{e.matched.get('timeline', 'from form')}')")
    dist = lead.get("distance_km")
    if dist is None:
        dist = e.distance_km
    if dist is not None:
        d = float(dist)
        if d <= 5:
            add("near_5km", f"{d:.1f} km from shop (<=5 km)")
        elif d <= 10:
            add("near_10km", f"{d:.1f} km from shop (<=10 km)")
        elif d > 20:
            add("far_20km", f"{d:.1f} km from shop (>20 km, delivery/visit cost)")
    if (lead.get("customer_type") or e.customer_type) == "contractor":
        add("contractor", "contractor / painter (repeat trade buyer)")
    if e.price_intent:
        add("price_intent", f"asked for price/rate ('{e.matched.get('price_intent')}')")
    if e.brands:
        add("brand_named", "named a brand/product: " + ", ".join(e.brands[:3]))
    if lead.get("source") in HIGH_INTENT_SOURCES:
        add("high_intent_source", f"high-intent source: {lead.get('source')}")
    total = max(0, min(100, total))
    bucket = "hot" if total >= HOT else "warm" if total >= WARM else "cold"
    lines.append(f"= {total} ({bucket}; hot>={HOT}, warm>={WARM})")
    return total, bucket, lines
