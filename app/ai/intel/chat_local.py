"""Локальный rank чатов — 0 токенов LLM."""

from __future__ import annotations

import re

from app.ai.intel.schema import ChatRank

_POS = re.compile(
    r"(?i)("
    r"клиент|client|чаттер|chatter|медиабай|media\s*buy|трафик|traffic|"
    r"аккаунт|account|оффер|offer|ставк|rate|процент|слот|slot|"
    r"нанима|hire|ищу\s*(партн|менедж|баер|байер)|купл\w*\s*траф|"
    r"ведение|retain|креатив|creative|воронк|funnel|арбитраж|arbitrage"
    r")"
)
_NEG = re.compile(
    r"(?i)("
    r"leetcode|homework|курсов\w*\s*python|учим\s*программ|"
    r"github\s*job|junior\s*dev|вакансия\s*разработ"
    r")"
)


def rank_chat_local(
    *,
    chat_id: int,
    title: str,
    about: str,
    posts: list[str],
) -> ChatRank:
    blob = f"{title}\n{about}\n" + "\n".join(posts[:40])
    pos = len(_POS.findall(blob))
    neg = len(_NEG.findall(blob))
    # длина/плотность переписки
    writers_proxy = min(30, max(1, len(posts) // 2))
    avg_len = (sum(len(p) for p in posts[:40]) / max(1, min(40, len(posts)))) if posts else 0
    score = 35
    score += min(40, pos * 6)
    score -= min(25, neg * 8)
    score += min(15, writers_proxy // 2)
    if avg_len > 80:
        score += 5
    if avg_len < 20 and pos == 0:
        score -= 10
    score = max(0, min(100, score))
    theme = "ops/deals" if pos > neg else ("dev" if neg else "mixed")
    return ChatRank(
        chat_id=chat_id,
        title=title,
        score=score,
        theme=theme,
        reason=f"local pos={pos} neg={neg}",
    )
