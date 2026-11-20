"""Tiny mobile-first HTML pages for shop staff (Hindi + English labels). No JS framework."""

from __future__ import annotations

import json
from html import escape
from typing import Any

from .db import Row
from .routing import OWNER_LABEL

CSS = """body{font-family:system-ui,sans-serif;margin:0;padding:1rem;max-width:640px;margin:auto;color:#1d2433}
a{color:#2456d6} label{display:block;margin:.7rem 0 .2rem;font-weight:600}
input,select,textarea{width:100%;font-size:1.05rem;padding:.55rem;box-sizing:border-box;border:1px solid #bbb;
border-radius:6px} button{font-size:1.05rem;padding:.65rem 1rem;margin:.3rem .2rem 0 0;border:0;border-radius:6px;
background:#2456d6;color:#fff} .card{border:1px solid #dde3ee;border-radius:8px;padding:.7rem;margin:.6rem 0}
.hot{border-left:6px solid #d33}.warm{border-left:6px solid #e9a400}.cold{border-left:6px solid #999}
small{color:#667} .row{display:flex;gap:.5rem} .row>*{flex:1} nav a{margin-right:1rem}"""


def page(title: str, body: str) -> str:
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" '
        f'content="width=device-width,initial-scale=1"><title>{escape(title)}</title><style>{CSS}</style>'
        f'</head><body><nav><a href="/staff">Leads / लीड</a><a href="/staff/new">+ New / नया</a>'
        f'<a href="/staff/baseline">Baseline log</a></nav><h2>{escape(title)}</h2>{body}</body></html>'
    )


def lead_list(leads: list[Row]) -> str:
    cards = []
    for r in leads:
        cards.append(
            f'<div class="card {escape(str(r.get("score_bucket") or "cold"))}"><a href="/staff/lead/{r["id"]}">'
            f"<b>{escape(str(r.get('name') or '—'))}</b></a> · {escape(str(r['source']))} · "
            f"{escape(str(r.get('status')))}<br><small>score {r.get('score')} · "
            f"{escape(OWNER_LABEL.get(str(r.get('owner')), '—'))} · {escape(str(r['created_at'])[:16])} UTC"
            f"{' · ✅ replied' if r.get('first_human_reply_at') else ' · ⏳ waiting / जवाब बाकी'}</small></div>"
        )
    return page("Leads / लीड", "".join(cards) or "<p>No leads yet / अभी कोई लीड नहीं।</p>")


def lead_detail(r: Row, events: list[Row], window_open: bool) -> str:
    explain = "".join(f"<li>{escape(x)}</li>" for x in json.loads(r.get("score_explain") or "[]"))
    facts = "".join(
        f"<li>{k}: <b>{escape(str(r[k]))}</b></li>"
        for k in (
            "project_type",
            "size_text",
            "area",
            "pincode",
            "distance_km",
            "timeline",
            "customer_type",
            "language",
            "consent_source",
            "route_reason",
        )
        if r.get(k) not in (None, "")
    )
    evs = "".join(
        f"<li><small>{escape(str(e['at'])[:19])} {escape(str(e['kind']))} {escape(str(e.get('channel') or ''))}"
        f"</small> {escape(str(e.get('body') or ''))[:300]}</li>"
        for e in events
    )
    phone = escape(str(r["phone"]))
    lid = r["id"]
    send = (
        '<label>WhatsApp reply / जवाब भेजें</label><textarea name="text" rows="3"></textarea>'
        '<button name="action" value="send">Send on WhatsApp</button>'
        if window_open and not r.get("opted_out")
        else "<p><small>WhatsApp window closed or opted out — call instead / कॉल करें.</small></p>"
    )
    body = f"""<p><b>{escape(str(r.get("name") or "—"))}</b> · <a href="tel:{phone}">{phone}</a> ·
<a href="https://wa.me/{phone.lstrip("+")}">WhatsApp</a></p>
<p>Owner: <b>{escape(OWNER_LABEL.get(str(r.get("owner")), "—"))}</b> · status <b>{escape(str(r["status"]))}</b>
{" · <b>OPTED OUT</b>" if r.get("opted_out") else ""}</p>
<ul>{facts}</ul><details><summary>Score {r.get("score")} — why</summary><ul>{explain}</ul></details>
<form method="post" action="/staff/lead/{lid}/action">
<button name="action" value="replied">✅ I replied / called — मैंने जवाब दिया</button>
{send}
<div class="row"><div><label>Quote ₹ / कोटेशन</label><input name="value" inputmode="numeric"></div></div>
<button name="action" value="quote">Quotation sent</button><button name="action" value="won">Won — invoice ₹</button>
<label>Lost reason / क्यों नहीं हुआ</label><input name="lost_reason">
<button name="action" value="lost" style="background:#777">Lost</button></form>
<h3>Timeline</h3><ul>{evs}</ul>"""
    return page("Lead", body)


SOURCES = [
    ("walk_in", "Walk-in / दुकान पर आए"),
    ("phone_call", "Phone call / फ़ोन"),
    ("gbp_call", "Google Maps call / गूगल से कॉल"),
    ("instagram", "Instagram DM"),
    ("facebook", "Facebook DM"),
    ("referral", "Referral / जान-पहचान"),
    ("other", "Other / अन्य"),
]
PROJECTS = [
    ("", "—"),
    ("interior", "Interior / अंदर"),
    ("exterior", "Exterior / बाहर"),
    ("waterproofing", "Waterproofing / सीलन"),
    ("wood_polish", "Wood polish / पॉलिश"),
]


def _opts(items: list[tuple[str, str]]) -> str:
    return "".join(f'<option value="{v}">{escape(lab)}</option>' for v, lab in items)


def manual_form(msg: str = "") -> str:
    return page(
        "New enquiry / नई पूछताछ",
        f"""<p>{escape(msg)}</p><form method="post">
<label>Mobile number / मोबाइल नंबर *</label><input name="phone" inputmode="tel" required>
<label>Name / नाम</label><input name="name">
<label>Where from? / कहाँ से?</label><select name="source">{_opts(SOURCES)}</select>
<label>Work / काम</label><select name="project_type">{_opts(PROJECTS)}</select>
<label>Area / एरिया</label><input name="area">
<label>Notes (size, budget, when) / नोट्स</label><textarea name="notes" rows="3"></textarea>
<label><input type="checkbox" name="responded" value="1" checked style="width:auto"> Already answered (in person / on
call) / जवाब दे दिया</label>
<label><input type="checkbox" name="consent" value="1" style="width:auto"> Customer agreed to WhatsApp messages /
ग्राहक WhatsApp मैसेज के लिए सहमत है</label>
<button>Save / सेव करें</button></form>""",
    )


OUTCOMES = [
    ("open", "Still open / बाकी"),
    ("quoted", "Quotation given / कोटेशन दिया"),
    ("won", "Sale / बिक्री हुई"),
    ("lost", "Lost / नहीं हुआ"),
]


def baseline_form(n: int, msg: str = "") -> str:
    return page(
        "Baseline log (before go-live) / पुराना तरीका लॉग",
        f"""<p>{escape(msg)}</p>
<p><small>Fill this for EVERY enquiry for 2 weeks before the system goes live. Entries so far: <b>{n}</b>.
हर पूछताछ के लिए 2 हफ्ते भरें।</small></p><form method="post">
<label>Where from? / कहाँ से?</label><select name="source">{_opts([("whatsapp", "WhatsApp"), *SOURCES])}</select>
<div class="row"><div><label>Enquiry date+time / कब आई</label><input type="datetime-local" name="lead_at" required>
</div><div><label>First reply time / पहला जवाब कब</label><input type="datetime-local" name="first_reply_at"></div></div>
<label>Outcome / नतीजा</label><select name="outcome">{_opts(OUTCOMES)}</select>
<div class="row"><div><label>Quote ₹</label><input name="quote_value" inputmode="numeric"></div>
<div><label>Invoice ₹</label><input name="invoice_value" inputmode="numeric"></div></div>
<label>Notes</label><input name="notes"><label>Logged by / किसने भरा</label><input name="logged_by">
<button>Save / सेव करें</button></form><p><a href="/staff/baseline.csv">Download CSV</a></p>""",
    )


def to_csv(rows: list[dict[str, Any]], cols: list[str]) -> str:
    import csv
    import io

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()
