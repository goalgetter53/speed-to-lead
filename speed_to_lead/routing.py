"""Who owns a lead. Three humans: father (shop counter), painter partner (site jobs), Hussain (digital)."""

from __future__ import annotations

from typing import Any

DIGITAL_SOURCES = {"website", "instagram", "facebook", "meta_lead_ad", "gbp", "whatsapp_direct", "ctwa_ad"}
OWNER_LABEL = {"father": "Shop (Papa)", "painter": "Painter partner", "hussain": "Hussain"}


def route(lead: dict[str, Any], bucket: str) -> tuple[str, str]:
    """Return (owner, reason). Rules are ordered; first match wins."""
    ctype = lead.get("customer_type")
    project = lead.get("project_type")
    dist = lead.get("distance_km")
    if ctype == "contractor":
        return "father", "contractor/painter -> trade pricing at the counter"
    if dist is not None and float(dist) > 15:
        return "hussain", f"outside service area ({float(dist):.0f} km) -> qualify online / delivery quote"
    if project == "waterproofing" or (
        project in {"interior", "exterior"} and (lead.get("size_text") or bucket == "hot")
    ):
        return "painter", "homeowner job needing site visit / application -> painter partner"
    if lead.get("source") in DIGITAL_SOURCES and not project:
        return "hussain", "digital lead with unclear need -> qualify on WhatsApp"
    return "father", "default -> shop counter"
