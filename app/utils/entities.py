from __future__ import annotations

import json
import re
from typing import Any

from telethon.tl import types

# UTF-16 length of this grapheme is 2 — стандартный placeholder для custom emoji в Telegram
_EMOJI_PLACEHOLDER = "😀"

# {e:5278611606756942667} или {{emoji:5278611606756942667}}
_EMOJI_MARKER_RE = re.compile(
    r"\{\{?\s*(?:e|emoji|ce|custom_emoji)\s*:\s*(\d+)\s*\}\}?",
    re.IGNORECASE,
)


def utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def from_aiogram_message(message: Any) -> tuple[str, list[dict[str, Any]]]:
    text = message.text or message.caption or ""
    raw = message.entities or message.caption_entities or []
    out: list[dict[str, Any]] = []
    for ent in raw:
        kind = ent.type
        if hasattr(kind, "value"):
            kind = kind.value
        item: dict[str, Any] = {
            "type": str(kind),
            "offset": int(ent.offset),
            "length": int(ent.length),
        }
        custom_id = getattr(ent, "custom_emoji_id", None)
        if custom_id:
            item["custom_emoji_id"] = str(custom_id)
        url = getattr(ent, "url", None)
        if url:
            item["url"] = url
        user = getattr(ent, "user", None)
        if user is not None:
            item["user_id"] = int(user.id)
        language = getattr(ent, "language", None)
        if language:
            item["language"] = language
        out.append(item)
    return text, out


def entities_loads(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def entities_dumps(entities: list[dict[str, Any]]) -> str:
    return json.dumps(entities, ensure_ascii=False)


def normalize_entities(entities: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Привести entities к каноничному виду (в т.ч. premium emoji по id)."""
    out: list[dict[str, Any]] = []
    for raw in entities or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "").strip().lower()
        emoji_id = (
            raw.get("custom_emoji_id")
            or raw.get("document_id")
            or raw.get("emoji_id")
            or raw.get("id")
        )
        if kind in {
            "custom_emoji",
            "messageentitycustomemoji",
            "custom_emoji_sticker",
            "premium_emoji",
            "premium",
            "emoji",
            "ce",
        } or (emoji_id and kind in {"", "custom"}):
            if not emoji_id:
                continue
            length = int(raw.get("length") or utf16_len(_EMOJI_PLACEHOLDER))
            out.append(
                {
                    "type": "custom_emoji",
                    "offset": int(raw.get("offset") or 0),
                    "length": length,
                    "custom_emoji_id": str(emoji_id),
                }
            )
            continue
        item = dict(raw)
        if "type" in item:
            item["type"] = str(item["type"])
        if "offset" in item:
            item["offset"] = int(item["offset"])
        if "length" in item:
            item["length"] = int(item["length"])
        out.append(item)
    return out


def expand_premium_markers(text: str) -> tuple[str, list[dict[str, Any]]]:
    """
    Заменить маркеры {e:ID} / {{emoji:ID}} на placeholder 😀
    и собрать entities custom_emoji (UTF-16 offset/length).
    """
    if not text:
        return "", []
    parts: list[str] = []
    entities: list[dict[str, Any]] = []
    pos = 0
    utf16_offset = 0
    for m in _EMOJI_MARKER_RE.finditer(text):
        before = text[pos : m.start()]
        parts.append(before)
        utf16_offset += utf16_len(before)
        emoji_id = m.group(1)
        parts.append(_EMOJI_PLACEHOLDER)
        length = utf16_len(_EMOJI_PLACEHOLDER)
        entities.append(
            {
                "type": "custom_emoji",
                "offset": utf16_offset,
                "length": length,
                "custom_emoji_id": str(emoji_id),
            }
        )
        utf16_offset += length
        pos = m.end()
    parts.append(text[pos:])
    return "".join(parts), entities


def prepare_offer_text(
    text: str,
    entities: list[dict[str, Any]] | None = None,
    *,
    expand_markers: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Подготовка текста оффера для сохранения:
    1) раскрыть {e:ID} маркеры;
    2) нормализовать явные entities;
    3) склеить (маркеры + переданные entities).
    """
    text = text or ""
    marker_ents: list[dict[str, Any]] = []
    if expand_markers and _EMOJI_MARKER_RE.search(text):
        text, marker_ents = expand_premium_markers(text)
    explicit = normalize_entities(entities)
    merged = marker_ents + explicit
    seen: set[tuple[int, str]] = set()
    unique: list[dict[str, Any]] = []
    for ent in merged:
        key = (
            int(ent.get("offset", 0)),
            str(ent.get("custom_emoji_id") or ent.get("type")),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(ent)
    unique.sort(key=lambda e: int(e.get("offset", 0)))
    return text, unique


def to_telethon_entities(entities: list[dict[str, Any]] | None) -> list[Any]:
    result: list[Any] = []
    for ent in normalize_entities(entities):
        kind = str(ent.get("type", ""))
        offset = int(ent.get("offset", 0))
        length = int(ent.get("length", 0))
        if kind in {"custom_emoji", "MessageEntityCustomEmoji", "custom_emoji_sticker"}:
            doc = int(ent.get("custom_emoji_id") or ent.get("document_id") or 0)
            if not doc:
                continue
            result.append(
                types.MessageEntityCustomEmoji(
                    offset=offset, length=length, document_id=doc
                )
            )
        elif kind in {"bold", "MessageEntityBold"}:
            result.append(types.MessageEntityBold(offset=offset, length=length))
        elif kind in {"italic", "MessageEntityItalic"}:
            result.append(types.MessageEntityItalic(offset=offset, length=length))
        elif kind in {"underline", "MessageEntityUnderline"}:
            result.append(types.MessageEntityUnderline(offset=offset, length=length))
        elif kind in {"strikethrough", "strike", "MessageEntityStrike"}:
            result.append(types.MessageEntityStrike(offset=offset, length=length))
        elif kind in {"spoiler", "MessageEntitySpoiler"}:
            result.append(types.MessageEntitySpoiler(offset=offset, length=length))
        elif kind in {"code", "MessageEntityCode"}:
            result.append(types.MessageEntityCode(offset=offset, length=length))
        elif kind in {"pre", "MessageEntityPre"}:
            result.append(
                types.MessageEntityPre(
                    offset=offset, length=length, language=ent.get("language") or ""
                )
            )
        elif kind in {"text_link", "text_url", "MessageEntityTextUrl"}:
            result.append(
                types.MessageEntityTextUrl(
                    offset=offset, length=length, url=ent.get("url") or ""
                )
            )
        elif kind in {"url", "MessageEntityUrl"}:
            result.append(types.MessageEntityUrl(offset=offset, length=length))
        elif kind in {"mention", "MessageEntityMention"}:
            result.append(types.MessageEntityMention(offset=offset, length=length))
        elif kind in {"text_mention", "MessageEntityMentionName"}:
            result.append(
                types.MessageEntityMentionName(
                    offset=offset,
                    length=length,
                    user_id=int(ent.get("user_id") or 0),
                )
            )
        elif kind in {"blockquote", "MessageEntityBlockquote"}:
            result.append(types.MessageEntityBlockquote(offset=offset, length=length))
    return result
