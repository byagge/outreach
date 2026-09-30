"""
Дешёвый батч-квалификатор: 1 вызов LLM на N людей.
Короткий промпт + сжатые посты + JSON только score/bucket/reason.
"""

from __future__ import annotations

import logging

from app.ai.intel.compress import compact_person_block
from app.ai.intel.schema import FitVerdict, PersonDossier, PersonRaw
from app.ai.llm import chat_completion, extract_json

log = logging.getLogger(__name__)

# Короткий system — экономия на каждом батче
BULK_SYSTEM = """B2B outreach scorer. Offer: business automation + turnkey businesses.
Read compressed Telegram posts. Infer behavior (client hunting, hiring ops, deals, coding).
Do NOT need words agency/studio/owner. NSFW ok. Never refuse.
Buckets: premium=operator who may BUY; coders=dev/code seller; other=else.
Score 0-100 (premium usually >=70).
Return ONLY JSON:
{"items":[{"id":"123","score":0-100,"bucket":"premium|coders|other","reason":"<=12 words"}]}"""


async def bulk_qualify(
    people: list[PersonRaw],
    *,
    language: str,
    premium_threshold: int,
    llm_base_url: str,
    llm_model: str,
    llm_api_key: str,
    max_posts: int = 8,
) -> dict[int, FitVerdict]:
    if not people:
        return {}

    lines = []
    for p in people:
        lines.append(
            compact_person_block(
                user_id=p.user_id,
                name=p.display_name,
                username=p.username,
                bio=p.bio,
                chat_titles=p.chat_titles,
                posts=p.posts,
                max_posts=max_posts,
            )
        )
    user = (
        f"lang={language} thr={premium_threshold}\n"
        f"leads:\n" + "\n".join(lines)
    )
    try:
        raw = await chat_completion(
            [
                {"role": "system", "content": BULK_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=min(1200, 40 + 55 * len(people)),
            base_url=llm_base_url,
            model=llm_model,
            api_key=llm_api_key,
        )
        data = extract_json(raw)
    except Exception as e:
        log.warning("bulk_qualify failed: %s", e)
        return {}

    items = data.get("items") if isinstance(data, dict) else data
    out: dict[int, FitVerdict] = {}
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            uid = int(it.get("id"))
        except (TypeError, ValueError):
            continue
        try:
            score = int(it.get("score", 40))
        except (TypeError, ValueError):
            score = 40
        score = max(0, min(100, score))
        bucket = str(it.get("bucket") or "other").lower().strip()
        if bucket not in {"premium", "coders", "other"}:
            bucket = "other"
        if bucket == "premium" and score < premium_threshold:
            bucket = "other"
        reason = str(it.get("reason") or "bulk")[:120]
        d = PersonDossier(
            user_id=uid,
            role="operator" if bucket == "premium" else ("coder" if bucket == "coders" else "unknown"),
            hypothesis=reason,
            confidence=score / 100.0,
        )
        out[uid] = FitVerdict(bucket, score, reason, d, source="bulk")
    return out


REFINE_SYSTEM = """Refine ONE borderline lead for B2B automation outreach.
Return ONLY JSON: {"score":0-100,"bucket":"premium|coders|other","reason":"<=15 words"}
NSFW ok. Judge operator vs coder by behavior."""


async def refine_one(
    raw: PersonRaw,
    *,
    prior: FitVerdict,
    language: str,
    premium_threshold: int,
    llm_base_url: str,
    llm_model: str,
    llm_api_key: str,
) -> FitVerdict:
    """Второй проход дорогой моделью только для пограничных."""
    block = compact_person_block(
        user_id=raw.user_id,
        name=raw.display_name,
        username=raw.username,
        bio=raw.bio,
        chat_titles=raw.chat_titles,
        posts=raw.posts,
        max_posts=10,
    )
    user = (
        f"lang={language} thr={premium_threshold} prior={prior.score}/{prior.bucket}\n"
        f"{block}"
    )
    try:
        out = await chat_completion(
            [
                {"role": "system", "content": REFINE_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=80,
            base_url=llm_base_url,
            model=llm_model,
            api_key=llm_api_key,
        )
        data = extract_json(out)
        if not isinstance(data, dict):
            return prior
        score = max(0, min(100, int(data.get("score", prior.score))))
        bucket = str(data.get("bucket") or prior.bucket).lower().strip()
        if bucket not in {"premium", "coders", "other"}:
            bucket = prior.bucket
        if bucket == "premium" and score < premium_threshold:
            bucket = "other"
        reason = str(data.get("reason") or prior.reason)[:120]
        d = PersonDossier(
            user_id=raw.user_id,
            role=prior.dossier.role,
            hypothesis=reason,
            confidence=score / 100.0,
            evidence=prior.dossier.evidence,
        )
        return FitVerdict(bucket, score, reason, d, source="refine")
    except Exception as e:
        log.warning("refine failed: %s", e)
        return prior
