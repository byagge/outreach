from __future__ import annotations

from app.utils.entities import (
    expand_premium_markers,
    normalize_entities,
    prepare_offer_text,
    to_telethon_entities,
    utf16_len,
)


def test_expand_marker_basic():
    text, ents = expand_premium_markers("Hi {e:5278611606756942667}!")
    assert "{e:" not in text
    assert "😀" in text
    assert len(ents) == 1
    assert ents[0]["type"] == "custom_emoji"
    assert ents[0]["custom_emoji_id"] == "5278611606756942667"
    assert ents[0]["offset"] == utf16_len("Hi ")
    assert ents[0]["length"] == utf16_len("😀")


def test_expand_double_brace_and_aliases():
    text, ents = expand_premium_markers("A {{emoji:111}} B {ce:222} C")
    assert len(ents) == 2
    assert ents[0]["custom_emoji_id"] == "111"
    assert ents[1]["custom_emoji_id"] == "222"
    assert text.count("😀") == 2


def test_normalize_aliases():
    ents = normalize_entities(
        [
            {"type": "premium_emoji", "offset": 0, "length": 2, "emoji_id": "99"},
            {"type": "custom_emoji", "offset": 3, "length": 2, "document_id": 88},
        ]
    )
    assert ents[0]["custom_emoji_id"] == "99"
    assert ents[1]["custom_emoji_id"] == "88"


def test_prepare_merges_markers_and_entities():
    text, ents = prepare_offer_text(
        "X {e:1}",
        [{"type": "bold", "offset": 0, "length": 1}],
    )
    assert "😀" in text
    kinds = {e["type"] for e in ents}
    assert "custom_emoji" in kinds
    assert "bold" in kinds


def test_prepare_can_skip_markers():
    text, ents = prepare_offer_text(
        "X {e:1}",
        [],
        expand_markers=False,
    )
    assert "{e:1}" in text
    assert ents == []


def test_to_telethon_custom_emoji():
    ents = to_telethon_entities(
        [
            {
                "type": "custom_emoji",
                "offset": 0,
                "length": 2,
                "custom_emoji_id": "5278611606756942667",
            }
        ]
    )
    assert len(ents) == 1
    assert ents[0].document_id == 5278611606756942667
