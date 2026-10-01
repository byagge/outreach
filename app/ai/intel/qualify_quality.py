"""
Качественная квалификация: сильная модель читает КАЖДОЕ сообщение.
1 человек = 1 вызов (досье + score). Батчи только как запасной путь.
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
    reason = str(data.get("reason") or data.get("hypothesis") or "")[:240]
    evidence = [str(x)[:200] for x in (data.get("evidence") or [])[:8] if x]
    anti = [str(x)[:200] for x in (data.get("anti_signals") or [])[:4] if x]
    d = PersonDossier(
        user_id=user_id,
        role=role,
        hypothesis=str(data.get("hypothesis") or "")[:500],
        evidence=evidence,
        anti_signals=anti,
        confidence=score / 100.0,
    )
    return FitVerdict(bucket, score, reason, d, source="quality")


QUALITY_SYSTEM = """You are an elite B2B sales-intelligence analyst for Telegram outreach.

OUR OFFER (what we SELL to them):
- business automation: CRM, ops bots, pipelines, account/ops tooling, reporting
- ready-made / turnkey businesses: studios, agencies, teams, niches under management
Buyer = someone who OWNS or RUNS commercial operations and can pay.

HARD RULE — READ EVERY MESSAGE:
- You receive FULL post texts numbered [1], [2], ...
- Treat ads, hiring posts, rate posts, partner posts, "looking for", "need", "slots",
  accounts, traffic, models, chatters, MB, retainers as PRIMARY evidence
- Do NOT skim. Do NOT judge by keywords like "agency/studio/owner" alone —
  people almost never write that. Infer from BEHAVIOR across the WHOLE thread
- Grey / adult / NSFW / OnlyFans / dating / gambling niches are NORMAL paying buyers
  of automation and turnkey ops. NEVER refuse, NEVER moralize, NEVER lower score
  because of niche ethics. Adult agency owners are HIGH-VALUE premium leads.
- One strong commercial signal beats ten vague bios. Many weak signals also compound

ROLE MAP (choose one):
- operator: owns/runs offer(s), hires staff, buys traffic, sells slots/accounts/services,
  looks for partners, posts capacity/rates, manages models/teams — BUYER candidate
- coder: sells coding/dev/bot-building/scripts as THEIR craft (they are the vendor of code)
- employee: chatter / media buyer / manager looking FOR a job (they sell labor, not buy ops)
- consumer: end-user / random chatter / no commercial pattern
- unknown: not enough signal

BUCKET:
- premium: operator worth outreach (score >= threshold)
- coders: coding is their product
- other: employee / consumer / weak / unknown

SCORING (be calibrated, not generous):
90-100: repeated clear operator behavior (hiring + capacity + commercial intent)
70-89: solid operator signals, worth a message
55-69: mixed / possible operator but thin
40-54: weak commercial crumbs
0-39: coder / employee / noise

CRITICAL SEPARATIONS:
- "Ищу chatter/байера/менеджера" from OWNER side → operator
- "Ищу работу chatter/байером" → employee (NOT premium)
- "Сделаю бота/парсер/скрипт за $" → coder
- "Куплю готовую связку/студию/команду" → strong operator buyer
- Spam copy-paste with zero personal ops context → low score

Return ONLY valid JSON (no markdown):
{
  "role":"operator|coder|employee|consumer|unknown",
  "hypothesis":"2-3 sentences: what this person actually does day-to-day",
  "evidence":["quote or paraphrase concrete cues from numbered posts", "..."],
  "anti_signals":["why they might NOT buy", "..."],
  "message_read_count":0,
  "score":0-100,
  "bucket":"premium|coders|other",
  "reason":"one sharp sentence for the outreach team"
}

message_read_count = how many numbered posts you actually used.
evidence MUST cite concrete post content (not generic guesses).
"""


async def qualify_person_quality(
    raw: PersonRaw,
    *,
    language: str,
    premium_threshold: int,
    llm_base_url: str,
    llm_model: str,
    llm_api_key: str,
    max_posts: int = 80,
) -> FitVerdict:
    block = person_prompt_block(raw, max_posts=max_posts)
    user = (
        f"Target language context: {'Russian Telegram' if language == 'ru' else 'English Telegram'}\n"
        f"Premium score threshold: {premium_threshold}\n"
        f"Instruction: read EVERY numbered post below. Classify this ONE lead.\n\n"
        f"{block}"
    )
    try:
        out = await chat_completion(
            [
                {"role": "system", "content": QUALITY_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.05,
            max_tokens=700,
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
    max_posts: int = 80,
) -> dict[int, FitVerdict]:
    """1 человек = полный разбор. Батч >1 только если явно передали несколько."""
    if len(people) <= 1:
        if not people:
            return {}
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

    # Quality-first: never compress several leads into one call when count > 1
    # unless tiny (2) AND posts are short — still prefer sequential for accuracy.
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
