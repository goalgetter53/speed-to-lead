"""Shop hours, quiet hours and 'next open' calculation (IST by default)."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import Settings

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DAY_NAMES = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "hi": ["सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"],
    "mr": ["सोमवार", "मंगळवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"],
}


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _closed_days(s: Settings) -> set[int]:
    return {_DAYS.index(d.strip().lower()[:3]) for d in s.shop_closed_days.split(",") if d.strip()}


def local(dt: datetime, s: Settings) -> datetime:
    return dt.astimezone(ZoneInfo(s.timezone))


def is_open(dt: datetime, s: Settings) -> bool:
    lt = local(dt, s)
    if lt.weekday() in _closed_days(s):
        return False
    return _t(s.shop_open) <= lt.time() < _t(s.shop_close)


def next_open(dt: datetime, s: Settings) -> datetime:
    """Next moment the shop is open at or after dt (returns dt itself if open now). UTC."""
    if is_open(dt, s):
        return dt
    tz = ZoneInfo(s.timezone)
    lt = local(dt, s)
    closed = _closed_days(s)
    for add in range(0, 8):
        day = (lt + timedelta(days=add)).date()
        if day.weekday() in closed:
            continue
        cand = datetime.combine(day, _t(s.shop_open), tzinfo=tz)
        if cand > lt:
            return cand.astimezone(UTC)
    raise ValueError("shop is never open; check STL_SHOP_CLOSED_DAYS")


def sla_start(inbound: datetime, s: Settings) -> datetime:
    """SLA clock starts at the inbound time if open, else at next opening."""
    return next_open(inbound, s)


def describe_next_open(dt: datetime, now: datetime, s: Settings, lang: str) -> str:
    lt, ln = local(dt, s), local(now, s)
    hhmm = lt.strftime("%I:%M %p").lstrip("0") if lang == "en" else lt.strftime("%H:%M")
    delta = (lt.date() - ln.date()).days
    if lang == "hi":
        day = "आज" if delta == 0 else "कल" if delta == 1 else _DAY_NAMES["hi"][lt.weekday()]
        return f"{day} सुबह {hhmm} बजे"
    if lang == "mr":
        day = "आज" if delta == 0 else "उद्या" if delta == 1 else _DAY_NAMES["mr"][lt.weekday()]
        return f"{day} सकाळी {hhmm} वाजता"
    day = "today" if delta == 0 else "tomorrow" if delta == 1 else _DAY_NAMES["en"][lt.weekday()]
    return f"{day} at {hhmm}"
