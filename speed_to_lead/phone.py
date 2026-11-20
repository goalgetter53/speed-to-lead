"""Phone normalisation to E.164 with India (+91) as the default country."""

from __future__ import annotations

import re

_DIGITS = re.compile(r"\d+")


def normalise(raw: str | None) -> str | None:
    """Return an E.164 string ("+919812345678") or None if it cannot be a phone number.

    Handles "98123 45678", "+91-98123-45678", "09812345678", "919812345678" (WhatsApp `from`),
    "0091 98123 45678" and Pune landlines "020 2687 1234". Non-Indian numbers must carry "+".
    """
    if not raw:
        return None
    s = raw.strip()
    plus = s.startswith("+") or s.startswith("00")
    digits = "".join(_DIGITS.findall(s))
    if s.startswith("00"):
        digits = digits[2:]
    if not digits:
        return None
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    if len(digits) == 11 and digits[0] == "0":
        return "+91" + digits[1:]
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    if plus and 8 <= len(digits) <= 15:
        return "+" + digits
    return None


def is_indian_mobile(e164: str) -> bool:
    return bool(re.fullmatch(r"\+91[6-9]\d{9}", e164))


def wa_id(e164: str) -> str:
    """WhatsApp Cloud API expects the number without '+'."""
    return e164.lstrip("+")


def mask(e164: str) -> str:
    """For logs / staff screens: +91 98xxxxxx78."""
    if len(e164) < 6:
        return "***"
    return e164[:5] + "x" * (len(e164) - 7) + e164[-2:]
