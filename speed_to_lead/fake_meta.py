"""Fake Meta Graph API + Telegram Bot API for the demo and local testing. Records everything it receives."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException, Request


@dataclass
class FakeMeta:
    sent: list[dict[str, Any]] = field(default_factory=list)  # WhatsApp messages
    telegram: list[dict[str, Any]] = field(default_factory=list)  # owner alerts
    leads: dict[str, dict[str, Any]] = field(default_factory=dict)  # leadgen_id -> lead object
    lock: threading.Lock = field(default_factory=threading.Lock)

    def app(self) -> FastAPI:
        app = FastAPI(title="fake-meta")

        @app.post("/{version}/{phone_number_id}/messages")
        async def messages(version: str, phone_number_id: str, request: Request) -> dict[str, Any]:
            body = await request.json()
            if not request.headers.get("authorization", "").startswith("Bearer "):
                raise HTTPException(401)
            mid = "wamid.FAKE" + uuid.uuid4().hex[:16]
            with self.lock:
                self.sent.append(
                    {
                        "to": body.get("to"),
                        "type": body.get("type"),
                        "payload": body,
                        "id": mid,
                        "t": time.perf_counter(),
                    }
                )
            return {
                "messaging_product": "whatsapp",
                "contacts": [{"wa_id": body.get("to")}],
                "messages": [{"id": mid}],
            }

        @app.get("/{version}/{leadgen_id}")
        def lead(version: str, leadgen_id: str) -> dict[str, Any]:
            if leadgen_id not in self.leads:
                raise HTTPException(404)
            return self.leads[leadgen_id]

        @app.post("/{bot}/sendMessage")
        async def tg(bot: str, request: Request) -> dict[str, Any]:
            body = await request.json()
            with self.lock:
                self.telegram.append(
                    {
                        "chat_id": body.get("chat_id"),
                        "text": body.get("text"),
                        "silent": body.get("disable_notification"),
                        "t": time.perf_counter(),
                    }
                )
            return {"ok": True, "result": {"message_id": len(self.telegram)}}

        return app

    def sent_to(self, wa_id: str) -> list[dict[str, Any]]:
        with self.lock:
            return [m for m in self.sent if m["to"] == wa_id]
