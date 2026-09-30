"""Сжатие постов перед LLM — меньше токенов без потери сигнала."""

from __future__ import annotations

import hashlib
import re

_NOISE = re.compile(
    r"^(ok|ок|ага|лол|lol|кек|хаха+|ахах+|👍|😂|🔥|💯|\+|да|нет|ну|хм+|м+| )\s*$",
    re.I,
)
_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    t = _WS.sub(" ", (text or "").strip())
    return t


def _fp(text: str) -> str:
    # отпечаток для дедупа похожих сообщений
    base = re.sub(r"\d+", "#", text.lower())
    base = re.sub(r"[^\w\sа-яё]", "", base, flags=re.I)
    return hashlib.md5(base[:160].encode("utf-8", errors="ignore")).hexdigest()[:12]


def select_posts_for_llm(
    posts: list[str],
    *,
    max_posts: int = 8,
    max_chars_each: int = 280,
    max_total_chars: int = 1600,
) -> list[str]:
    """
    Берём самые информативные посты:
    - без шума (ок/лол/эмодзи)
    - без дублей
    - длиннее = полезнее (до лимита)
    - свежие первыми (вход = от новых к старым из Telethon)
    """
    picked: list[str] = []
    seen: set[str] = set()
    total = 0

    # сначала свежие, потом добьём длинными из хвоста
    candidates: list[tuple[int, str]] = []
    for p in posts:
        t = _norm(p)
        if len(t) < 12 or _NOISE.match(t):
            continue
        fp = _fp(t)
        if fp in seen:
            continue
        seen.add(fp)
        if len(t) > max_chars_each:
            t = t[: max_chars_each - 1] + "…"
        # score: длина + наличие коммерческих маркеров (дешёвый буст отбора, не классификация)
        boost = 0
        low = t.lower()
        for tip in (
            "клиент",
            "client",
            "ставк",
            "rate",
            "найм",
            "hire",
            "чаттер",
            "chatter",
            "трафик",
            "traffic",
            "аккаунт",
            "account",
            "оффер",
            "offer",
            "процент",
            "слот",
            "slot",
            "ищу",
            "looking",
            "купл",
            "buy",
            "прода",
            "sell",
        ):
            if tip in low:
                boost += 40
                break
        candidates.append((len(t) + boost, t))

    # свежие уже в порядке posts; пересортируем по полезности, но сохраним немного порядка
    # берём top по score
    candidates.sort(key=lambda x: x[0], reverse=True)
    for _, t in candidates:
        if len(picked) >= max_posts:
            break
        if total + len(t) > max_total_chars and picked:
            break
        picked.append(t)
        total += len(t)
    return picked


def compact_person_block(
    *,
    user_id: int,
    name: str,
    username: str,
    bio: str,
    chat_titles: list[str],
    posts: list[str],
    max_posts: int = 8,
) -> str:
    """Минимальный текстовый блок на человека для батч-LLM."""
    selected = select_posts_for_llm(posts, max_posts=max_posts)
    parts = [f"id={user_id}"]
    if name:
        parts.append(f"n={name[:40]}")
    if username:
        parts.append(f"@{username}")
    if bio:
        parts.append(f"bio={bio[:120]}")
    if chat_titles:
        parts.append("ch=" + ",".join(chat_titles[:3])[:80])
    if selected:
        parts.append("p=" + " || ".join(selected))
    else:
        parts.append("p=")
    return " | ".join(parts)
