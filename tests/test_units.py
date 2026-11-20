from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from speed_to_lead import hours
from speed_to_lead.config import Settings
from speed_to_lead.enrich import Enrichment, detect_language, enrich, llm_classify, merge_into_lead
from speed_to_lead.messages import first_reply, is_opt_out, pick_questions
from speed_to_lead.phone import is_indian_mobile, mask, normalise
from speed_to_lead.routing import route
from speed_to_lead.scoring import score
from speed_to_lead.whatsapp import (
    Inbound,
    WhatsAppClient,
    parse_leadgen,
    parse_messages,
    sign,
    verify_signature,
)

from .conftest import IST

S = Settings()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("98123 45678", "+919812345678"),
        ("+91-98123-45678", "+919812345678"),
        ("09812345678", "+919812345678"),
        ("919812345678", "+919812345678"),
        ("0091 98123 45678", "+919812345678"),
        ("020 2687 1234", "+912026871234"),
        ("+44 7700 900123", "+447700900123"),
        ("12345", None),
        ("", None),
        (None, None),
        ("5812345678", None),
    ],
)
def test_normalise(raw: str | None, expected: str | None) -> None:
    assert normalise(raw) == expected


def test_mobile_and_mask() -> None:
    assert is_indian_mobile("+919812345678") and not is_indian_mobile("+912026871234")
    assert mask("+919812345678") == "+9198xxxxxx78"


def test_enrich_hindi_seepage() -> None:
    e = enrich("छत से पानी टपक रहा है, सीलन है। Undri 411060, 2BHK. rate kitna hai? jaldi chahiye", S)
    assert (e.language, e.project_type, e.size_text, e.pincode, e.area, e.timeline) == (
        "hi",
        "waterproofing",
        "2BHK",
        "411060",
        "Undri",
        "now",
    )
    assert e.price_intent and e.distance_km is not None and e.distance_km < 1


def test_enrich_english_interior_and_budget() -> None:
    e = enrich("Need Asian Paints Royale for 3 BHK interior in NIBM, my flat, budget 1.5 lakh, next month", S)
    assert e.project_type == "interior" and e.big_home and e.customer_type == "homeowner"
    assert e.budget_rupees == 150_000 and e.timeline == "later" and e.area == "NIBM"
    assert "asian paints" in e.brands and "royale" in e.brands


def test_enrich_marathi_contractor_and_sqft() -> None:
    e = enrich("आमच्या बंगल्याचे बाहेरील रंगकाम करायचे आहे, किती खर्च?", S)
    assert e.language == "mr" and e.project_type == "exterior" and e.big_home
    c = enrich("Painter hoon, 1500 sq ft site Kondhwa, dealer rate chahiye, budget 50k", S)
    assert (
        c.customer_type == "contractor" and c.big_home and c.budget_rupees == 50_000 and c.area == "Kondhwa"
    )


def test_enrich_word_boundaries() -> None:
    e = enrich("I updated my website campaign", S)  # 'site' / 'camp' must not match inside words
    assert e.customer_type is None and e.area is None
    assert detect_language("hello") == "en"


def test_merge_only_fills_empty() -> None:
    e = Enrichment(project_type="interior", area="Undri")
    assert merge_into_lead(
        {"project_type": "exterior", "area": None, "language": "hi"}, e, {"timeline": "now"}
    ) == {"area": "Undri", "timeline": "now"}


def test_llm_disabled_and_mocked() -> None:
    assert llm_classify("x", S) == {}
    s = Settings(llm_api_key="k")

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"project_type":"exterior","area":null,"junk":"x"}'}}]
            },
        )

    out = llm_classify("bahar ka kaam", s, httpx.Client(transport=httpx.MockTransport(handler)))
    assert out == {"project_type": "exterior"}
    err = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert llm_classify("x", s, err) == {}


def test_score_lines_sum() -> None:
    e = enrich("waterproofing 2BHK Undri jaldi rate", S)
    lead = {"source": "walk_in", "distance_km": e.distance_km}
    total, bucket, lines = score(lead, e)
    assert sum(int(x.split()[0]) for x in lines[:-1]) == total and bucket == "hot"
    assert lines[-1].startswith(f"= {total}")
    t2, b2, _ = score({"source": "website"}, enrich("hello", S))
    assert (t2, b2) == (10, "cold")


@pytest.mark.parametrize(
    "lead,owner",
    [
        ({"customer_type": "contractor", "distance_km": 30}, "father"),
        ({"distance_km": 24, "project_type": "waterproofing"}, "hussain"),
        ({"project_type": "waterproofing"}, "painter"),
        ({"project_type": "interior", "size_text": "2BHK"}, "painter"),
        ({"source": "website"}, "hussain"),
        ({"source": "walk_in", "project_type": "interior"}, "father"),
    ],
)
def test_route(lead: dict[str, object], owner: str) -> None:
    assert route(lead, "warm")[0] == owner


def test_hours() -> None:
    s = Settings(shop_closed_days="sun")
    sat_night = datetime(2026, 11, 21, 22, 0, tzinfo=IST)
    assert not hours.is_open(sat_night, s)
    nxt = hours.next_open(sat_night, s)
    assert nxt.astimezone(IST) == datetime(2026, 11, 23, 9, 30, tzinfo=IST)  # skips Sunday
    assert hours.describe_next_open(nxt, sat_night, s, "en") == "Monday at 9:30 AM"
    assert hours.describe_next_open(nxt, sat_night, s, "hi").startswith("सोमवार")
    open_t = datetime(2026, 11, 20, 12, 0, tzinfo=IST)
    assert hours.is_open(open_t, s) and hours.next_open(open_t, s) == open_t
    early = datetime(2026, 11, 20, 7, 0, tzinfo=IST)
    assert hours.describe_next_open(hours.next_open(early, s), early, s, "mr") == "आज सकाळी 09:30 वाजता"


def test_signature() -> None:
    body = b'{"a":1}'
    assert verify_signature("sec", body, sign("sec", body))
    assert not verify_signature("sec", body, sign("other", body))
    assert not verify_signature("sec", body, None) and not verify_signature("", body, sign("", body))


def test_parse_messages_types_and_attribution() -> None:
    def m(**kw: object) -> dict[str, object]:
        return {"from": "919812345678", "id": f"w{len(str(kw))}", "timestamp": "1700000000", **kw}

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "contacts": [{"wa_id": "919812345678", "profile": {"name": "A"}}],
                            "messages": [
                                m(type="text", text={"body": "hi (ref:gbp)"}),
                                m(type="button", button={"text": "Call me today"}),
                                m(type="interactive", interactive={"button_reply": {"title": "Yes"}}),
                                m(type="image", image={"caption": "wall photo"}),
                                m(type="text", text={"body": "ad"}, referral={"source_id": "AD1"}),
                            ],
                            "statuses": [{"id": "x"}],
                        },
                    }
                ]
            }
        ],
    }
    msgs = parse_messages(payload)
    assert [x.text for x in msgs] == ["hi (ref:gbp)", "Call me today", "Yes", "[image] wall photo", "ad"]
    assert msgs[0].source() == ("gbp", "gbp") and msgs[4].source() == ("ctwa_ad", "AD1")
    assert msgs[1].source() == ("whatsapp_direct", None) and msgs[0].name == "A"
    assert parse_messages({"object": "page"}) == []
    lg = parse_leadgen(
        {"object": "page", "entry": [{"changes": [{"field": "leadgen", "value": {"leadgen_id": "1"}}]}]}
    )
    assert lg == [{"leadgen_id": "1"}]


def test_client_dry_run_and_http() -> None:
    assert WhatsAppClient(Settings(dry_run=True)).send_text("+919812345678", "x").dry_run
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})

    s = Settings(dry_run=False, wa_phone_number_id="PN", wa_access_token="T", graph_version="v23.0")
    res = WhatsAppClient(s, httpx.Client(transport=httpx.MockTransport(handler))).send_text(
        "+919812345678", "hi"
    )
    assert res.ok and res.message_id == "wamid.1"
    assert seen[0].url.path == "/v23.0/PN/messages" and seen[0].headers["authorization"] == "Bearer T"
    assert b'"to":"919812345678"' in seen[0].content.replace(b" ", b"")
    bad = WhatsAppClient(
        s, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, text="no")))
    )
    assert not bad.send_template("+919812345678", "t", "en", ["a"]).ok


def test_messages() -> None:
    assert pick_questions({"project_type": "interior"}) == ["size_text", "area"]
    txt = first_reply({}, "hi", "United Trader", "https://c", False, "कल सुबह 09:30 बजे")
    assert "दुकान बंद" in txt and "STOP" in txt and "https://c" in txt
    assert is_opt_out("Stop") and is_opt_out("बंद करो") and not is_opt_out("don't stop the work")
    assert Inbound("w", "1", "x", datetime.now(IST)).source() == ("whatsapp_direct", None)
