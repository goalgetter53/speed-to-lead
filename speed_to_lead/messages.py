"""Customer-facing and owner-facing message texts (English / Hindi / Marathi).

These are *session* (free-form) messages, only ever sent inside the 24h window the customer opened.
Meta-approved *templates* for business-initiated messages live in templates/whatsapp_templates.json.
"""

from __future__ import annotations

from typing import Any

QUESTIONS: dict[str, dict[str, str]] = {
    "project_type": {
        "en": "What work is it: interior, exterior, waterproofing/seepage or wood polish?",
        "hi": "कौन सा काम है: अंदर की पेंटिंग, बाहर की पेंटिंग, वॉटरप्रूफिंग/सीलन या लकड़ी की पॉलिश?",
        "mr": "कोणते काम आहे: आतील रंगकाम, बाहेरील रंगकाम, वॉटरप्रूफिंग/गळती की लाकडी पॉलिश?",
    },
    "size_text": {
        "en": "How big is it? (e.g. 2BHK, 1 room, or approx sq ft)",
        "hi": "जगह कितनी बड़ी है? (जैसे 2BHK, 1 कमरा, या लगभग sq ft)",
        "mr": "जागा किती मोठी आहे? (उदा. 2BHK, 1 खोली, किंवा अंदाजे sq ft)",
    },
    "area": {
        "en": "Which area / pincode is the site in?",
        "hi": "साइट किस एरिया / पिनकोड में है?",
        "mr": "साइट कोणत्या भागात / पिनकोडमध्ये आहे?",
    },
    "timeline": {
        "en": "When do you want to start?",
        "hi": "काम कब शुरू करना है?",
        "mr": "काम कधी सुरू करायचे आहे?",
    },
    "customer_type": {
        "en": "Is this for your own home, or are you a contractor/painter?",
        "hi": "यह आपके अपने घर के लिए है, या आप ठेकेदार/पेंटर हैं?",
        "mr": "हे तुमच्या स्वतःच्या घरासाठी आहे, की तुम्ही ठेकेदार/पेंटर आहात?",
    },
}
QUESTION_ORDER = ["project_type", "size_text", "area", "timeline", "customer_type"]

STOP_FOOTER = {
    "en": "Reply STOP to stop messages.",
    "hi": "मैसेज बंद करने के लिए STOP लिखें।",
    "mr": "मेसेज बंद करण्यासाठी STOP पाठवा.",
}


def pick_questions(lead: dict[str, Any], n: int = 2) -> list[str]:
    return [k for k in QUESTION_ORDER if not lead.get(k)][:n]


def first_reply(
    lead: dict[str, Any], lang: str, shop: str, catalogue_url: str, open_now: bool, next_open_text: str
) -> str:
    lang = lang if lang in ("en", "hi", "mr") else "en"
    qs = [QUESTIONS[k][lang] for k in pick_questions(lead)]
    qlines = "\n".join(f"{i}. {q}" for i, q in enumerate(qs, 1))
    if lang == "hi":
        head = f"नमस्ते! {shop} (उंड्री, पुणे) से संपर्क करने के लिए धन्यवाद 🙏"
        status = (
            "हमारी टीम कुछ ही मिनट में जवाब देगी।" if open_now else f"अभी दुकान बंद है। हम {next_open_text} जवाब देंगे।"
        )
        price = f"रेट लिस्ट / कैटलॉग: {catalogue_url}"
        ask = "जल्दी सही रेट देने के लिए बताइए:"
    elif lang == "mr":
        head = f"नमस्कार! {shop} (उंड्री, पुणे) शी संपर्क केल्याबद्दल धन्यवाद 🙏"
        status = (
            "आमची टीम काही मिनिटांत उत्तर देईल."
            if open_now
            else f"सध्या दुकान बंद आहे. आम्ही {next_open_text} उत्तर देऊ."
        )
        price = f"दरपत्रक / कॅटलॉग: {catalogue_url}"
        ask = "लवकर योग्य दर देण्यासाठी सांगा:"
    else:
        head = f"Hello! Thanks for contacting {shop} (Undri, Pune) 🙏"
        status = (
            "Our team will reply in a few minutes."
            if open_now
            else f"The shop is closed right now. We will reply {next_open_text}."
        )
        price = f"Price list / catalogue: {catalogue_url}"
        ask = "To give you the right rate quickly, please tell us:"
    parts = [head, status, price]
    if qs:
        parts += [ask, qlines]
    parts.append(STOP_FOOTER[lang])
    return "\n\n".join(parts)


def followup(lang: str, n: int, catalogue_url: str) -> str:
    if lang == "hi":
        return (
            (
                "क्या आपको अभी भी पेंट/वॉटरप्रूफिंग के लिए मदद चाहिए? साइज़ और एरिया भेज दीजिए, हम रेट बता देंगे। "
                f"कैटलॉग: {catalogue_url}\n\n{STOP_FOOTER['hi']}"
            )
            if n == 1
            else (
                f"आज आख़िरी याद दिला रहे हैं — कोई सवाल हो तो यहीं लिखिए या दुकान पर कॉल कीजिए। {STOP_FOOTER['hi']}"
            )
        )
    if lang == "mr":
        return (
            (
                "तुम्हाला अजूनही रंग/वॉटरप्रूफिंगसाठी मदत हवी आहे का? साइज आणि भाग पाठवा, आम्ही दर सांगू. "
                f"कॅटलॉग: {catalogue_url}\n\n{STOP_FOOTER['mr']}"
            )
            if n == 1
            else (f"आजची शेवटची आठवण — काही प्रश्न असल्यास इथेच लिहा किंवा दुकानात फोन करा. {STOP_FOOTER['mr']}")
        )
    return (
        (
            f"Still need help with paint or waterproofing? Send the size and area and we'll share the rate. "
            f"Catalogue: {catalogue_url}\n\n{STOP_FOOTER['en']}"
        )
        if n == 1
        else (
            f"Last reminder from us today: any questions, just reply here or call the shop. {STOP_FOOTER['en']}"
        )
    )


OPT_OUT_CONFIRM = {
    "en": "You won't get more messages from us. Send START anytime to message us again.",
    "hi": "अब आपको हमारी तरफ़ से मैसेज नहीं आएँगे। दोबारा शुरू करने के लिए START भेजें।",
    "mr": "आता तुम्हाला आमच्याकडून मेसेज येणार नाहीत. पुन्हा सुरू करण्यासाठी START पाठवा.",
}
OPT_IN_CONFIRM = {
    "en": "Welcome back! How can we help?",
    "hi": "फिर से स्वागत है! बताइए, क्या मदद करें?",
    "mr": "पुन्हा स्वागत आहे! काय मदत करू?",
}

OPT_OUT_WORDS = {"stop", "unsubscribe", "stop all", "band karo", "बंद करो", "बंद", "थांबवा", "nako", "नको"}
OPT_IN_WORDS = {"start", "unstop", "शुरू", "सुरू"}


def is_opt_out(text: str) -> bool:
    return text.strip().lower().strip(".!") in OPT_OUT_WORDS


def is_opt_in(text: str) -> bool:
    return text.strip().lower().strip(".!") in OPT_IN_WORDS


def owner_alert(lead: dict[str, Any], kind: str, link: str, open_now: bool) -> str:
    who = lead.get("name") or "New customer"
    facts = ", ".join(str(lead[k]) for k in ("project_type", "size_text", "area", "timeline") if lead.get(k))
    head = {
        "new": "🟢 NEW LEAD / नया ग्राहक",
        "call_now": "📞 CALL NOW (form lead) / अभी कॉल करें",
        "sla1": "⏰ No reply in 5 min / 5 मिनट में जवाब नहीं",
        "sla2": "🚨 ESCALATION: no reply in 15 min / 15 मिनट में जवाब नहीं",
    }[kind]
    tail = "" if open_now else "\n(Shop closed — reply after opening / दुकान खुलने पर जवाब दें)"
    return (
        f"{head}\n{who} · {lead.get('source')} · score {lead.get('score')} ({lead.get('score_bucket')})\n"
        f"{facts or 'details pending'}\n{link}{tail}"
    )
