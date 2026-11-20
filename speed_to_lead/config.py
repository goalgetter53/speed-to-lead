"""Settings loaded from environment variables. No secrets live in the repo."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from typing import Any

OWNER_KEYS = ("father", "painter", "hussain")


def _bool(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    database_url: str = "sqlite:///./data/stl.db"
    # Meta / WhatsApp Cloud API
    wa_verify_token: str = ""
    wa_app_secret: str = ""
    wa_access_token: str = ""
    wa_phone_number_id: str = ""
    meta_page_token: str = ""  # leads_retrieval; a system-user token can cover WhatsApp + leads
    wa_business_number: str = ""  # digits only, e.g. 9190xxxxxxxx (shown in wa.me links)
    graph_base_url: str = "https://graph.facebook.com"
    graph_version: str = "v23.0"
    dry_run: bool = True  # True: never call Meta/Telegram, just log what would be sent
    allow_paid_templates: bool = False  # free-only by default
    service_msg_monthly_cap: int = 950  # stop automation before Meta's free allowance runs out
    # Shop
    shop_name: str = "United Trader"
    shop_area: str = "Undri, Pune"
    shop_pincode: str = "411060"
    shop_lat: float = 18.4553  # approximate; set exact shop coordinates in env
    shop_lon: float = 73.9154
    shop_open: str = "09:30"
    shop_close: str = "20:30"
    shop_closed_days: str = ""  # e.g. "sun" or "tue,sun"
    timezone: str = "Asia/Kolkata"
    catalogue_url: str = "https://example.com/united-trader-price-list"  # owner replaces
    # SLA
    sla_human_minutes: int = 5
    sla_escalate_minutes: int = 15
    followup_hours: str = "2,22"  # hours after auto-reply, must be < 24 (free service window)
    sla_loop_seconds: int = 30  # 0 disables in-process loop (use /cron/tick instead)
    cron_secret: str = ""
    # Owners (WhatsApp numbers and Telegram chat ids)
    owner_father_wa: str = ""
    owner_painter_wa: str = ""
    owner_hussain_wa: str = ""
    telegram_bot_token: str = ""
    telegram_base_url: str = "https://api.telegram.org"
    telegram_father_chat: str = ""
    telegram_painter_chat: str = ""
    telegram_hussain_chat: str = ""
    # Staff web pages
    public_base_url: str = "http://localhost:8000"
    leadform_optin_field: str = "whatsapp_opt_in"  # custom question name on the Meta lead form
    synthetic_mode: bool = False  # demo: every lead created is flagged synthetic
    staff_user: str = "staff"
    staff_password: str = ""
    form_allowed_origins: str = ""
    # Optional LLM classification (off unless key set)
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        src = dict(os.environ) if env is None else env
        s = cls()
        for f in fields(cls):
            if f.name == "extra":
                continue
            key = "STL_" + f.name.upper()
            if key not in src:
                continue
            raw = src[key]
            cur = getattr(s, f.name)
            val: Any
            if isinstance(cur, bool):
                val = _bool(raw)
            elif isinstance(cur, int):
                val = int(raw)
            elif isinstance(cur, float):
                val = float(raw)
            else:
                val = raw
            setattr(s, f.name, val)
        return s

    def owner_wa(self, owner: str) -> str:
        return str(getattr(self, f"owner_{owner}_wa", ""))

    def owner_telegram(self, owner: str) -> str:
        return str(getattr(self, f"telegram_{owner}_chat", ""))

    def followups(self) -> list[float]:
        return [float(x) for x in self.followup_hours.split(",") if x.strip()]
