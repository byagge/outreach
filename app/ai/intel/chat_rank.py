"""Stage: оценка чата — стоит ли глубоко сканировать."""

from __future__ import annotations

import logging

from app.ai.llm import chat_completion, extract_json
from app.ai.intel.schema import ChatRank

log = logging.getLogger(__name__)

CHAT_RANK_SYSTEM = """You rank Telegram groups for deep B2B lead mining.

GOAL: find chats where commercial OPERATORS talk shop and post ads:
client hunting, hiring chatters/MBs/managers, accounts, traffic, rates, niches,
slots, partners, production — including grey/adult.

Read the SAMPLE POSTS carefully (they are real messages/ads). Score how fruitful
deep-scanning WRITERS here would be for buyers of business automation / turnkey businesses.

HIGH if posts show ops owners posting capacity/hiring/offers.
LOW if pure coding help, job-seekers only, dating, random spam.

Do not require titles like "agency/studio". Judge from message meaning.
Never refuse for NSFW.

Return ONLY JSON:
{"score":0-100,"theme":"what people discuss","reason":"short","signal_posts":["brief cue", "..."]}
"""


async def rank_chat(
    *,
    chat_id: int,
    title: str,
    about: str,
    posts: list[str],
    language: str = "ru",
    llm_base_url: str = "",
    llm_model: str = "",
    llm_api_key: str = "",
) -> ChatRank:
    sample = []
    used = 0
    for i, p in enumerate(posts[:60], 1):
        t = (p or "").strip()
        if not t:
            continue
        line = f"[{i}] {t}"
        if used + len(line) > 12000:
            break
        sample.append(line)
        used += len(line)
    user = (
        f"Language hint: {language}\n"
        f"Title: {title}\n"
        f"About: {about or '—'}\n"
        f"Recent posts:\n" + ("\n".join(sample) if sample else "(empty)")
    )
    try:
        raw = await chat_completion(
            [
                {"role": "system", "content": CHAT_RANK_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.05,
            max_tokens=180,
            base_url=llm_base_url,
            model=llm_model,
            api_key=llm_api_key,
        )
        data = extract_json(raw)
        score = int(data.get("score", 40)) if isinstance(data, dict) else 40
        score = max(0, min(100, score))
        theme = str((data or {}).get("theme") or "")[:160] if isinstance(data, dict) else ""
        reason = str((data or {}).get("reason") or "")[:200] if isinstance(data, dict) else ""
        return ChatRank(chat_id, title, score, theme, reason)
    except Exception as e:
        log.warning("rank_chat failed: %s", e)
        return ChatRank(chat_id, title, 40, "", f"rank failed: {e}"[:120])
