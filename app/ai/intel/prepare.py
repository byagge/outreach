"""Подготовка постов для LLM: только мусор и точные дубли убираем. Смысл не режем."""

from __future__ import annotations

import hashlib
import re

_NOISE = re.compile(
    r"^(ok|ок|ага|лол|lol|кек|хаха+|ахах+|👍|😂|🔥|💯|\+|да|нет|ну|хм+)\s*$",
    re.I,
)
_WS = re.compile(r"\s+")


def prepare_posts(
    posts: list[str],
    *,
    max_posts: int = 50,
    max_total_chars: int = 14000,
) -> list[str]:
    """
    Полные тексты постов.
    Убираем только: пустое, однословный шум, точные дубли.
    НЕ обрезаем сообщения и НЕ выкидываем «неключевые».
    """
    out: list[str] = []
    seen: set[str] = set()
    total = 0
    for p in posts:
        t = _WS.sub(" ", (p or "").strip())
        if len(t) < 8 or _NOISE.match(t):
            continue
        fp = hashlib.md5(t.lower().encode("utf-8", errors="ignore")).hexdigest()
        if fp in seen:
            continue
        seen.add(fp)
        if total + len(t) > max_total_chars and out:
            break
        out.append(t)
        total += len(t)
        if len(out) >= max_posts:
            break
    return out


def person_prompt_block(raw, *, max_posts: int = 50) -> str:
    from app.ai.intel.schema import PersonRaw

    assert isinstance(raw, PersonRaw)
    posts = prepare_posts(raw.posts, max_posts=max_posts)
    lines = [
        f"id: {raw.user_id}",
        f"name: {raw.display_name or '—'}",
        f"username: @{raw.username}" if raw.username else "username: —",
        f"bio: {raw.bio or '—'}",
        f"chats: {', '.join(raw.chat_titles[:12]) or '—'}",
        f"posts_full ({len(posts)}):",
    ]
    for i, t in enumerate(posts, 1):
        lines.append(f"[{i}] {t}")
    return "\n".join(lines)
