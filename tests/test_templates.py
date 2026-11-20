from __future__ import annotations

import json
import re
from pathlib import Path

TEMPLATES = Path(__file__).parent.parent / "templates" / "whatsapp_templates.json"


def test_templates_follow_meta_rules() -> None:
    data = json.loads(TEMPLATES.read_text(encoding="utf-8"))["templates"]
    names = {t["name"] for t in data}
    assert len(names) == 4 and {t["language"] for t in data} == {"en", "hi"}
    for t in data:
        assert re.fullmatch(r"[a-z0-9_]{1,512}", t["name"])
        body = next(c for c in t["components"] if c["type"] == "BODY")
        text = body["text"]
        nums = [int(n) for n in re.findall(r"\{\{(\d+)\}\}", text)]
        assert nums == list(range(1, len(nums) + 1)), t["name"]  # sequential variables
        assert not re.match(r"\s*\{\{", text) and not re.search(r"\}\}\s*$", text)  # not at start/end
        assert len(body["example"]["body_text"][0]) == len(nums)
        assert len(text) <= 1024
        if "owner" not in t["name"]:  # customer-facing templates must offer opt-out
            assert "STOP" in json.dumps(t, ensure_ascii=False)
