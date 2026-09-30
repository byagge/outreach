"""
Качественная квалификация: 1 сильный LLM-вызов на человека (или крошечный батч).
Полные посты. Досье + score в одном ответе — без потери смысла.
"""

from __future__ import annotations

import logging

from app.ai.intel.prepare import person_prompt_block
from app.ai.intel.schema import FitVerdict, PersonDossier, PersonRaw
from app.ai.llm import chat_completion, extract_json

log = logging.getLogger(__name__)

def _verdict_from_llm_item(
    user_id: int,
    data: dict,
    *,
    premium_threshold: int,
) -> FitVerdict:
    """Shared guards for single + batch LLM responses (must stay identical)."""
    role = str(data.get("role") or "unknown").lower().strip()
    if role not in {"operator", "coder", "employee", "consumer", "unknown"}:
        role = "unknown"
    try:
        score = int(data.get("score", 40))
    except (TypeError, ValueError):
        score = 40
    score = max(0, min(100, score))
    bucket = str(data.get("bucket") or "other").lower().strip()
    if bucket not in {"premium", "coders", "other"}:
        bucket = "other"
    if role == "coder":
        bucket = "coders"
        score = min(score, 45)
    if bucket == "premium" and score < premium_threshold:
        bucket = "other"
    if bucket == "premium" and role in {"employee", "consumer"}:
        bucket = "other"
    reason = str(data.get("reason") or data.get("hypothesis") or "")[:200]
    evidence = [str(x)[:160] for x in (data.get("evidence") or [])[:5] if x]
    anti = [str(x)[:160] for x in (data.get("anti_signals") or [])[:3] if x]
    d = PersonDossier(
        user_id=user_id,
        role=role,
        hypothesis=str(data.get("hypothesis") or "")[:400],
        evidence=evidence,
        anti_signals=anti,
        confidence=score / 100.0,
    )
    return FitVerdict(bucket, score, reason, d, source="quality")


QUALITY_SYSTEM = """You are a senior B2B sales-intelligence analyst (OpenAI/Anthropic grade).

OFFER: business automation (ops/CRM/bots/pipelines) + ready-made/turnkey businesses.

REALITY IN TELEGRAM:
People almost never write "I am an agency/studio/owner".
Operators show it by BEHAVIOR: hunting clients, hiring chatters/media buyers/managers,
rates, slots, accounts, niches, traffic, partners, capacity, retainers.
Coders show coding/dev freelancing/bot-building as the product itself.
Grey/NSFW niches are normal — never refuse, never moralize.

TASK: Read ALL full posts. Infer who they are and whether they would BUY our offer.

Return ONLY JSON:
{
  "role":"operator|coder|employee|consumer|unknown",
  "hypothesis":"2 sentences: what they actually do",
  "evidence":["concrete cues from posts", "..."],
  "anti_signals":["why they might not buy"],
  "score":0-100,
  "bucket":"premium|coders|other",
  "reason":"one sentence"
}

SCORING:
90-100 clear operator + buying context
70-89 likely operator worth outreach
40-69 mixed/weak
0-39 coder / employee / noise
premium requires score>=threshold AND operator-like behavior.
If coding is their main craft → bucket=coders even if they sell "services".
"""


async def qualify_person_quality(
    raw: PersonRaw,
    *,
    language: str,
    premium_threshold: int,
    llm_base_url: str,
    llm_model: str,
    llm_api_key: str,
    max_posts: int = 50,
) -> FitVerdict:
    block = person_prompt_block(raw, max_posts=max_posts)
    user = (
        f"Language: {'Russian' if language == 'ru' else 'English'}\n"
        f"Premium threshold: {premium_threshold}\n\n"
        f"{block}"
    )
    try:
        out = await chat_completion(
            [
                {"role": "system", "content": QUALITY_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.05,
            max_tokens=450,
            base_url=llm_base_url,
            model=llm_model,
            api_key=llm_api_key,
        )
        data = extract_json(out)
    except Exception as e:
        log.warning("qualify_person_quality uid=%s: %s", raw.user_id, e)
        return FitVerdict(
            "other",
            30,
            f"llm error: {e}"[:120],
            PersonDossier(raw.user_id, "unknown", "llm error"),
            source="error",
        )

    if not isinstance(data, dict):
        return FitVerdict(
            "other", 30, "bad json", PersonDossier(raw.user_id), source="error"
        )
    return _verdict_from_llm_item(raw.user_id, data, premium_threshold=premium_threshold)


async def qualify_batch_quality(
    people: list[PersonRaw],
    *,
    language: str,
    premium_threshold: int,
    llm_base_url: str,
    llm_model: str,
    llm_api_key: str,
    max_posts: int = 50,
) -> dict[int, FitVerdict]:
    """Маленький батч (2–4) с полными постами — если 1 человек, тоже ок."""
    if len(people) == 1:
        v = await qualify_person_quality(
            people[0],
            language=language,
            premium_threshold=premium_threshold,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            llm_api_key=llm_api_key,
            max_posts=max_posts,
        )
        return {people[0].user_id: v}

    blocks = []
    for p in people:
        blocks.append(person_prompt_block(p, max_posts=max_posts))
    user = (
        f"Language: {'Russian' if language == 'ru' else 'English'}\n"
        f"Premium threshold: {premium_threshold}\n"
        f"Classify EACH lead. Return ONLY:\n"
        f'{{"items":[{{"id":"<id>","role":"...","hypothesis":"...","evidence":[],'
        f'"anti_signals":[],"score":0-100,"bucket":"premium|coders|other","reason":"..."}}]}}\n\n'
        + "\n\n====\n\n".join(blocks)
    )
    try:
        out = await chat_completion(
            [
                {"role": "system", "content": QUALITY_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.05,
            max_tokens=min(2000, 200 + 350 * len(people)),
            base_url=llm_base_url,
            model=llm_model,
            api_key=llm_api_key,
        )
        data = extract_json(out)
    except Exception as e:
        log.warning("batch quality failed, fallback one-by-one: %s", e)
        result: dict[int, FitVerdict] = {}
        for p in people:
            result[p.user_id] = await qualify_person_quality(
                p,
                language=language,
                premium_threshold=premium_threshold,
                llm_base_url=llm_base_url,
                llm_model=llm_model,
                llm_api_key=llm_api_key,
                max_posts=max_posts,
            )
        return result

    items = data.get("items") if isinstance(data, dict) else None
    result = {}
    if isinstance(items, list):
        by_id = {str(p.user_id): p for p in people}
        for it in items:
            if not isinstance(it, dict):
                continue
            sid = str(it.get("id") or "")
            # id may be inside nested — also try int
            p = by_id.get(sid)
            if not p:
                try:
                    p = by_id.get(str(int(sid)))
                except (TypeError, ValueError):
                    p = None
            if not p:
                continue
            result[p.user_id] = _verdict_from_llm_item(
                p.user_id, it, premium_threshold=premium_threshold
            )

    for p in people:
        if p.user_id not in result:
            result[p.user_id] = await qualify_person_quality(
                p,
                language=language,
                premium_threshold=premium_threshold,
                llm_base_url=llm_base_url,
                llm_model=llm_model,
                llm_api_key=llm_api_key,
                max_posts=max_posts,
            )
    return result
