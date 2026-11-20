"""Owner notifications. Telegram is free and unlimited, so it is the default channel.

WhatsApp to an owner is only sent as a free session message when that owner has messaged the business
number within the last 24h (send "hi" every morning). Otherwise it would need a paid template.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from .config import Settings
from .db import Store
from .whatsapp import Sender


@dataclass
class Notice:
    owner: str
    channel: str
    ok: bool
    detail: str = ""


class Notifier:
    def __init__(self, s: Settings, store: Store, wa: Sender, http: httpx.Client | None = None) -> None:
        self.s, self.store, self.wa = s, store, wa
        self.http = http or httpx.Client(timeout=10.0)

    def notify(self, owner: str, text: str, now: datetime, silent: bool = False) -> list[Notice]:
        out: list[Notice] = []
        chat = self.s.owner_telegram(owner)
        if chat and self.s.telegram_bot_token:
            if self.s.dry_run:
                out.append(Notice(owner, "telegram", True, "dry_run"))
            else:
                try:
                    r = self.http.post(
                        f"{self.s.telegram_base_url}/bot{self.s.telegram_bot_token}/sendMessage",
                        json={"chat_id": chat, "text": text, "disable_notification": silent},
                    )
                    out.append(Notice(owner, "telegram", r.status_code < 400, f"HTTP {r.status_code}"))
                except httpx.HTTPError as exc:
                    out.append(Notice(owner, "telegram", False, repr(exc)))
        wa = self.s.owner_wa(owner)
        last = self.store.owner_last_ping(owner)
        if wa and last and now - last < timedelta(hours=23, minutes=50):
            res = self.wa.send_text(wa, text)
            out.append(Notice(owner, "whatsapp", res.ok, res.error or ""))
        if not out:
            out.append(Notice(owner, "none", False, "no channel configured / owner WA window closed"))
        return out
