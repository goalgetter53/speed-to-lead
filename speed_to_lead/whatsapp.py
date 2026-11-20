"""WhatsApp Cloud API: webhook signature check, payload parsing, and a minimal send client."""

from __future__ import annotations

import hashlib
import hmac
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from .config import Settings

REF_RE = re.compile(r"\(ref:([a-z0-9_-]{2,20})\)", re.I)
REF_SOURCES = {
    "gbp": "gbp",
    "web": "website",
    "ig": "instagram",
    "fb": "facebook",
    "walkin": "walk_in",
    "qr": "walk_in",
    "flyer": "flyer",
}


def verify_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    """Meta signs the raw body: X-Hub-Signature-256: sha256=<hex hmac(app_secret, body)>."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def sign(app_secret: str, raw_body: bytes) -> str:
    return "sha256=" + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()


@dataclass
class Inbound:
    wamid: str
    wa_from: str
    text: str
    timestamp: datetime
    name: str | None = None
    msg_type: str = "text"
    referral: dict[str, Any] = field(default_factory=dict)

    def source(self) -> tuple[str, str | None]:
        """Attribution: Click-to-WhatsApp ad referral, else a (ref:xx) tag pre-filled in wa.me links."""
        if self.referral:
            return "ctwa_ad", str(self.referral.get("source_id") or self.referral.get("source_url") or "")
        m = REF_RE.search(self.text)
        if m:
            tag = m.group(1).lower()
            base = tag.split("-")[0]
            return REF_SOURCES.get(base, "whatsapp_direct"), tag
        return "whatsapp_direct", None


def _text_of(msg: dict[str, Any]) -> str:
    t = msg.get("type")
    if t == "text":
        return str(msg.get("text", {}).get("body", ""))
    if t == "button":
        return str(msg.get("button", {}).get("text", ""))
    if t == "interactive":
        it = msg.get("interactive", {})
        reply = it.get("button_reply") or it.get("list_reply") or {}
        return str(reply.get("title", ""))
    caption = (msg.get(t or "", {}) or {}).get("caption") if isinstance(msg.get(t or ""), dict) else None
    return f"[{t}] {caption}" if caption else f"[{t}]"


def parse_messages(payload: dict[str, Any]) -> list[Inbound]:
    out: list[Inbound] = []
    if payload.get("object") != "whatsapp_business_account":
        return out
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            for msg in value.get("messages", []):  # 'statuses' (delivery receipts) are ignored
                out.append(
                    Inbound(
                        wamid=str(msg["id"]),
                        wa_from=str(msg["from"]),
                        text=_text_of(msg),
                        timestamp=datetime.fromtimestamp(int(msg.get("timestamp", 0)), UTC),
                        name=names.get(msg["from"]),
                        msg_type=str(msg.get("type", "text")),
                        referral=dict(msg.get("referral") or {}),
                    )
                )
    return out


@dataclass
class SendResult:
    ok: bool
    message_id: str | None = None
    error: str | None = None
    dry_run: bool = False


class Sender(Protocol):
    def send_text(self, to_e164: str, body: str) -> SendResult: ...

    def send_template(self, to_e164: str, name: str, lang: str, params: list[str]) -> SendResult: ...


class WhatsAppClient:
    def __init__(self, s: Settings, client: httpx.Client | None = None) -> None:
        self.s = s
        self.http = client or httpx.Client(timeout=10.0)

    def _post(self, payload: dict[str, Any]) -> SendResult:
        if self.s.dry_run:
            return SendResult(ok=True, message_id="dryrun." + uuid.uuid4().hex[:12], dry_run=True)
        url = f"{self.s.graph_base_url}/{self.s.graph_version}/{self.s.wa_phone_number_id}/messages"
        try:
            r = self.http.post(
                url, json=payload, headers={"Authorization": f"Bearer {self.s.wa_access_token}"}
            )
            if r.status_code >= 400:
                return SendResult(ok=False, error=f"HTTP {r.status_code}: {r.text[:300]}")
            return SendResult(ok=True, message_id=str(r.json()["messages"][0]["id"]))
        except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
            return SendResult(ok=False, error=repr(exc))

    def send_text(self, to_e164: str, body: str) -> SendResult:
        return self._post(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to_e164.lstrip("+"),
                "type": "text",
                "text": {"preview_url": True, "body": body},
            }
        )

    def send_template(self, to_e164: str, name: str, lang: str, params: list[str]) -> SendResult:
        comps = (
            [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}] if params else []
        )
        return self._post(
            {
                "messaging_product": "whatsapp",
                "to": to_e164.lstrip("+"),
                "type": "template",
                "template": {"name": name, "language": {"code": lang}, "components": comps},
            }
        )


def fetch_leadgen(s: Settings, leadgen_id: str, client: httpx.Client | None = None) -> dict[str, Any]:
    """Meta Lead Ads: GET /{leadgen_id} with a Page access token that has leads_retrieval."""
    http = client or httpx.Client(timeout=10.0)
    r = http.get(
        f"{s.graph_base_url}/{s.graph_version}/{leadgen_id}",
        params={"fields": "created_time,field_data,ad_id,form_id,platform,is_organic"},
        headers={"Authorization": f"Bearer {s.meta_page_token or s.wa_access_token}"},
    )
    r.raise_for_status()
    data: dict[str, Any] = r.json()
    return data


def parse_leadgen(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if payload.get("object") != "page":
        return out
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") == "leadgen":
                out.append(dict(change.get("value", {})))
    return out


def leadgen_fields(lead: dict[str, Any]) -> dict[str, str]:
    """Flatten field_data [{name, values:[..]}] -> {name: first value}."""
    return {str(f.get("name")): str((f.get("values") or [""])[0]) for f in lead.get("field_data", [])}
