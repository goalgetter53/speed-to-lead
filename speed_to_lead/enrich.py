"""Rule-based enrichment from free text in English, Hindi, Marathi (Devanagari or transliterated).

Every extracted field records the keyword that triggered it, so the score explanation can quote it.
Optional LLM classification only fills fields the rules left empty, and only if STL_LLM_API_KEY is set.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from .config import Settings

AREAS_CSV = Path(__file__).parent / "data" / "pune_areas.csv"

# keyword -> label. Latin keywords match on word boundaries (case-insensitive); Devanagari as substrings.
PROJECT_KEYWORDS: dict[str, list[str]] = {
    "waterproofing": [
        "waterproof",
        "waterproofing",
        "water proofing",
        "seepage",
        "leakage",
        "leak",
        "leaking",
        "damp",
        "dampness",
        "seelan",
        "silan",
        "seelapan",
        "terrace",
        "dr fixit",
        "dr. fixit",
        "smartcare",
        "damp proof",
        "pani tapak",
        "paani tapak",
        "galti",
        "olawa",
        "सीलन",
        "रिसाव",
        "लीकेज",
        "टपक",
        "गळती",
        "ओल",
        "वॉटरप्रूफ",
    ],
    "exterior": [
        "exterior",
        "outside wall",
        "outer wall",
        "external",
        "bahar",
        "baher",
        "apex",
        "ultima",
        "weathercoat",
        "weathershield",
        "duralife",
        "elevation",
        "बाहर",
        "बाहेर",
        "एक्सटीरियर",
        "बाहेरील",
    ],
    "wood_polish": [
        "wood",
        "polish",
        "pu polish",
        "melamine",
        "lacquer",
        "sealer",
        "door",
        "doors",
        "furniture",
        "darwaja",
        "darwaza",
        "almari",
        "पॉलिश",
        "दरवाजा",
        "दरवाज़ा",
        "फर्निचर",
        "फर्नीचर",
        "लकड़ी",
        "लाकूड",
    ],
    "interior": [
        "interior",
        "inside",
        "bedroom",
        "hall",
        "kitchen",
        "living room",
        "royale",
        "tractor",
        "apcolite",
        "silk",
        "velvet touch",
        "easy clean",
        "impressions",
        "emulsion",
        "distemper",
        "andar",
        "aatil",
        "अंदर",
        "आतील",
        "कमरा",
        "खोली",
        "हॉल",
    ],
}
BRAND_KEYWORDS = [
    "asian paints",
    "asian paint",
    "berger",
    "nerolac",
    "dulux",
    "indigo",
    "birla opus",
    "jsw",
    "dr fixit",
    "royale",
    "apex",
    "ultima",
    "tractor",
    "apcolite",
    "smartcare",
    "weathercoat",
    "एशियन",
]
PRICE_KEYWORDS = [
    "rate",
    "rates",
    "price",
    "prices",
    "cost",
    "kitna",
    "kitne",
    "kiti",
    "bhav",
    "quotation",
    "quote",
    "estimate",
    "per litre",
    "per liter",
    "कीमत",
    "किंमत",
    "रेट",
    "भाव",
    "दाम",
    "कितना",
    "किती",
]
CONTRACTOR_KEYWORDS = [
    "contractor",
    "painter",
    "thekedar",
    "thekedaar",
    "site",
    "sites",
    "bulk",
    "dealer rate",
    "builder",
    "project rate",
    "maistry",
    "mistri",
    "ठेकेदार",
    "पेंटर",
    "कॉन्ट्रॅक्टर",
    "बिल्डर",
]
HOMEOWNER_KEYWORDS = [
    "my flat",
    "my house",
    "my home",
    "our flat",
    "our house",
    "mera ghar",
    "hamara ghar",
    "majha ghar",
    "aamcha ghar",
    "amcha ghar",
    "own house",
    "मेरा घर",
    "हमारा घर",
    "माझे घर",
    "आमचे घर",
    "माझा फ्लॅट",
]
TIMELINE_KEYWORDS: dict[str, list[str]] = {
    "now": [
        "urgent",
        "urgently",
        "asap",
        "today",
        "tomorrow",
        "this week",
        "aaj",
        "kal",
        "jaldi",
        "lavkar",
        "ya athavdyat",
        "is hafte",
        "आज",
        "कल",
        "उद्या",
        "जल्दी",
        "लवकर",
        "तुरंत",
    ],
    "soon": [
        "next week",
        "this month",
        "agle hafte",
        "is mahine",
        "pudhchya athavdyat",
        "diwali",
        "before festival",
        "within a month",
        "15 days",
        "अगले हफ्ते",
        "इस महीने",
        "दिवाळी",
        "दिवाली",
        "पुढच्या आठवड्यात",
    ],
    "later": [
        "next month",
        "after monsoon",
        "agle mahine",
        "pudhchya mahinyat",
        "just checking",
        "later",
        "अगले महीने",
        "पुढच्या महिन्यात",
        "बाद में",
        "नंतर",
    ],
}
HI_MARKERS = [
    "है",
    "चाहिए",
    "करना",
    "मुझे",
    "हमें",
    "कितना",
    "क्या",
    "hai",
    "chahiye",
    "karna",
    "mujhe",
    "kitna",
    "kya",
    "hume",
    "humko",
    "bhai",
]
MR_MARKERS = [
    "आहे",
    "पाहिजे",
    "करायचे",
    "करायचं",
    "मला",
    "आम्हाला",
    "किती",
    "काय",
    "aahe",
    "ahe",
    "pahije",
    "karaycha",
    "karaychay",
    "mala",
    "amhala",
    "kiti",
    "kay",
    "dada",
]

SIZE_RE = re.compile(r"\b([1-6])\s*-?\s*(bhk|rk)\b", re.I)
SQFT_RE = re.compile(r"\b(\d{2,6})\s*(sq\.?\s*ft|sqft|square\s*feet|sq\s*feet|स्क्वेअर फूट|वर्ग फुट)", re.I)
BIG_HOME_RE = re.compile(
    r"\b(bungalow|row\s*house|villa|duplex|independent house|building|society)\b|बंगल|बंगला", re.I
)
PIN_RE = re.compile(r"\b(4[01]\d{4})\b")
BUDGET_RE = re.compile(
    r"(?:₹|rs\.?|inr|budget|बजट|बजेट)\s*:?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|lakh|lac|l|हजार|लाख)?"
    r"|\b(\d+(?:\.\d+)?)\s*(k|lakh|lac|हजार|लाख)\b",
    re.I,
)


@dataclass
class Enrichment:
    language: str = "en"
    project_type: str | None = None
    size_text: str | None = None
    big_home: bool = False
    budget_text: str | None = None
    budget_rupees: int | None = None
    timeline: str | None = None
    customer_type: str | None = None
    area: str | None = None
    pincode: str | None = None
    distance_km: float | None = None
    brands: list[str] = field(default_factory=list)
    price_intent: bool = False
    matched: dict[str, str] = field(default_factory=dict)  # field -> keyword that matched

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _has(text: str, kw: str) -> bool:
    if kw.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", text) is not None
    return kw in text


def _first(text: str, kws: list[str]) -> str | None:
    for kw in kws:
        if _has(text, kw):
            return kw
    return None


def detect_language(text: str) -> str:
    low = text.lower()
    mr = sum(_has(low, m) for m in MR_MARKERS)
    hi = sum(_has(low, m) for m in HI_MARKERS)
    if mr > hi and mr > 0:
        return "mr"
    if hi > 0 or re.search(r"[ऀ-ॿ]", text):
        return "hi"
    return "en"


@lru_cache(maxsize=1)
def _places() -> tuple[list[tuple[str, list[str], float, float]], dict[str, tuple[str, float, float]]]:
    areas: list[tuple[str, list[str], float, float]] = []
    pins: dict[str, tuple[str, float, float]] = {}
    with AREAS_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            lat, lon = float(r["lat"]), float(r["lon"])
            if r["kind"] == "area":
                areas.append((r["key"], r["aliases"].split("|"), lat, lon))
            else:
                pins[r["key"]] = (r["aliases"], lat, lon)
    return areas, pins


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _budget(text: str) -> tuple[str, int] | None:
    m = BUDGET_RE.search(text)
    if not m:
        return None
    num = m.group(1) or m.group(3)
    unit = (m.group(2) or m.group(4) or "").lower()
    value = float(num.replace(",", ""))
    if unit in {"k", "हजार"}:
        value *= 1_000
    elif unit in {"lakh", "lac", "l", "लाख"}:
        value *= 100_000
    if value < 500:  # "2 k" style noise / litre counts
        return None
    return m.group(0).strip(), int(value)


def enrich(text: str, s: Settings) -> Enrichment:
    low = text.lower()
    e = Enrichment(language=detect_language(text))
    for label, kws in PROJECT_KEYWORDS.items():  # dict order = priority (waterproofing first)
        kw = _first(low, kws)
        if kw:
            e.project_type, e.matched["project_type"] = label, kw
            break
    m = SIZE_RE.search(text) or SQFT_RE.search(text)
    if m:
        e.size_text, e.matched["size_text"] = m.group(0).strip(), m.group(0).strip()
        if SIZE_RE.fullmatch(m.group(0).strip()) and int(m.group(1)) >= 3:
            e.big_home = True
        if m.re is SQFT_RE and int(m.group(1)) >= 1200:
            e.big_home = True
    big = BIG_HOME_RE.search(text)
    if big:
        e.big_home = True
        e.size_text = e.size_text or big.group(0)
        e.matched.setdefault("size_text", big.group(0))
    b = _budget(text)
    if b:
        e.budget_text, e.budget_rupees = b
        e.matched["budget_text"] = b[0]
    for label, kws in TIMELINE_KEYWORDS.items():
        kw = _first(low, kws)
        if kw:
            e.timeline, e.matched["timeline"] = label, kw
            break
    kw = _first(low, CONTRACTOR_KEYWORDS)
    if kw:
        e.customer_type, e.matched["customer_type"] = "contractor", kw
    else:
        kw = _first(low, HOMEOWNER_KEYWORDS)
        if kw:
            e.customer_type, e.matched["customer_type"] = "homeowner", kw
    e.brands = [b for b in BRAND_KEYWORDS if _has(low, b)]
    kw = _first(low, PRICE_KEYWORDS)
    if kw:
        e.price_intent, e.matched["price_intent"] = True, kw
    areas, pins = _places()
    pm = PIN_RE.search(text)
    lat_lon: tuple[float, float] | None = None
    if pm:
        e.pincode = pm.group(1)
        if e.pincode in pins:
            area, lat, lon = pins[e.pincode]
            e.area, lat_lon = area, (lat, lon)
    if e.area is None:
        for key, aliases, lat, lon in areas:
            hit = _first(low, aliases)
            if hit:
                e.area, lat_lon, e.matched["area"] = key, (lat, lon), hit
                break
    if lat_lon:
        e.distance_km = round(haversine_km(s.shop_lat, s.shop_lon, *lat_lon), 1)
    return e


LLM_FIELDS = ("project_type", "size_text", "budget_text", "timeline", "customer_type", "area")


def llm_classify(text: str, s: Settings, client: httpx.Client | None = None) -> dict[str, str]:
    """Optional: ask an OpenAI-compatible model for missing fields. Returns {} when disabled or on error."""
    if not s.llm_api_key:
        return {}
    prompt = (
        "Extract from this paint-shop enquiry (English/Hindi/Marathi). Reply JSON only with keys "
        "project_type (interior|exterior|waterproofing|wood_polish|null), size_text, budget_text, "
        "timeline (now|soon|later|null), customer_type (homeowner|contractor|null), area. Text: " + text
    )
    c = client or httpx.Client(timeout=8.0)
    try:
        r = c.post(
            f"{s.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {s.llm_api_key}"},
            json={
                "model": s.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
        )
        r.raise_for_status()
        data = json.loads(r.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        return {}
    return {k: str(v) for k, v in data.items() if k in LLM_FIELDS and v not in (None, "", "null")}


def merge_into_lead(lead: dict[str, Any], e: Enrichment, llm: dict[str, str] | None = None) -> dict[str, Any]:
    """Fields to update: only fill what is still empty (first answer wins; staff can overwrite)."""
    out: dict[str, Any] = {}
    candidates: dict[str, Any] = {
        "language": e.language if not lead.get("language") else None,
        "project_type": e.project_type,
        "size_text": e.size_text,
        "budget_text": e.budget_text,
        "timeline": e.timeline,
        "customer_type": e.customer_type,
        "area": e.area,
        "pincode": e.pincode,
        "distance_km": e.distance_km,
    }
    for k, v in (llm or {}).items():
        if candidates.get(k) is None:
            candidates[k] = v
    for k, v in candidates.items():
        if v is not None and lead.get(k) in (None, ""):
            out[k] = v
    return out
