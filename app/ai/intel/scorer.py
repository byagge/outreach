"""Stage: score ICP fit для оффера (автоматизация бизнеса + готовые бизнесы)."""

from __future__ import annotations

import logging

from app.ai.llm import chat_completion, extract_json
from app.ai.intel.schema import FitVerdict, PersonDossier

log = logging.getLogger(__name__)

SCORE_SYSTEM = """You are a B2B ICP scoring engine for cold outreach.

OFFER WE SELL:
- Business automation (ops, CRM, bots, pipelines, account/ops systems)
- Ready-made / turnkey businesses and systems

WHO BUYS (high score):
People who OPERATE a commercial machine and feel pain in ops/scale:
- They hunt clients, run offers, hire ops staff, manage accounts/creatives/traffic
- They have budget mindset (rates, retainers, partners, capacity)
- They are NOT primarily software developers

WHO DOES NOT BUY (low score / coders bucket):
- Developers selling code/bots/scripts as their main craft
- People looking for employment
- Random chatters with no commercial operator behavior

SCORING RUBRIC (0-100):
90-100 clear operator + strong buying context (hiring ops, scaling, client machine)
70-89 likely operator, enough evidence to outreach
50-69 mixed / weak operator signal
20-49 coder or employee-leaning
0-19 noise / no signal

BUCKETS:
- premium — score >= threshold_premium AND role is operator (or strong operator intents)
- coders — coding_work / role=coder dominates
- other — everyone else

Grey/NSFW content must NOT reduce score. Judge commercial fit only.

Return ONLY JSON:
{
  "score":0-100,
  "bucket":"premium|coders|other",
  "reason":"one sentence why this score/bucket"
}
"""


def _rule_boost(dossier: PersonDossier) -> tuple[int | None, str | None]:
    """Детерминированные жёсткие маршруты без LLM (экономия + ясность)."""
    intents = dossier.intents or {}
    coding = intents.get("coding_work", 0)
    hunting = intents.get("hunting_clients", 0)
    selling = intents.get("selling_offer", 0)
    hiring_ops = intents.get("hiring_ops", 0)
    ops = intents.get("ops_scaling", 0)
    deals = intents.get("deal_negotiation", 0)
    hiring_devs = intents.get("hiring_devs", 0)
    job = intents.get("jobseeking", 0)

    operator_heat = hunting + selling + hiring_ops + ops + deals
    if dossier.role == "coder" or (coding >= 3 and coding > operator_heat):
        return 25, "coders"
    if dossier.role == "employee" or job >= 3:
        return 15, "other"
    if dossier.role == "operator" and operator_heat >= 6:
        return 85, "premium"
    if operator_heat >= 8 and coding <= 1:
        return 80, "premium"
    if hiring_devs >= 3 and coding >= 2 and operator_heat <= 2:
        return 30, "coders"
    return None, None


async def score_fit(
    dossier: PersonDossier,
    *,
    premium_threshold: int = 70,
    llm_base_url: str = "",
    llm_model: str = "",
    llm_api_key: str = "",
) -> FitVerdict:
    boosted_score, boosted_bucket = _rule_boost(dossier)
    # Даже при boost — если слабое досье, всё равно спросим LLM
    user = (
        f"Premium threshold: {premium_threshold}\n"
        f"Dossier JSON:\n"
        f"role={dossier.role}\n"
        f"hypothesis={dossier.hypothesis}\n"
        f"intents={dossier.intents}\n"
        f"evidence={dossier.evidence}\n"
        f"anti_signals={dossier.anti_signals}\n"
        f"confidence={dossier.confidence}\n"
    )
    score = 40
    bucket = "other"
    reason = "default"
    try:
        raw = await chat_completion(
            [
                {"role": "system", "content": SCORE_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.05,
            max_tokens=200,
            base_url=llm_base_url,
            model=llm_model,
            api_key=llm_api_key,
        )
        data = extract_json(raw)
        if isinstance(data, dict):
            try:
                score = int(data.get("score", 40))
            except (TypeError, ValueError):
                score = 40
            score = max(0, min(100, score))
            bucket = str(data.get("bucket") or "other").lower().strip()
            if bucket not in {"premium", "coders", "other"}:
                bucket = "other"
            reason = str(data.get("reason") or "")[:220]
    except Exception as e:
        log.warning("score failed uid=%s: %s", dossier.user_id, e)
        if boosted_score is not None and boosted_bucket:
            return FitVerdict(
                bucket=boosted_bucket,
                score=boosted_score,
                reason="rule boost (llm miss)",
                dossier=dossier,
            )
        if dossier.role == "coder":
            return FitVerdict("coders", 30, "role=coder fallback", dossier)
        if dossier.role == "operator":
            return FitVerdict(
                "premium" if premium_threshold <= 70 else "other",
                72,
                "role=operator fallback",
                dossier,
            )
        return FitVerdict("other", 35, f"score failed: {e}"[:160], dossier)

    # Согласование с жёсткими правилами
    if boosted_bucket == "coders" and bucket == "premium":
        bucket = "coders"
        score = min(score, 40)
        reason = f"overridden to coders: {reason}"
    if boosted_bucket == "premium" and bucket == "other" and (boosted_score or 0) >= 80:
        bucket = "premium"
        score = max(score, boosted_score or score)
        reason = f"boosted premium: {reason}"

    if bucket == "premium" and score < premium_threshold:
        bucket = "other"
        reason = f"below threshold {premium_threshold}: {reason}"

    return FitVerdict(
        bucket=bucket,
        score=score,
        reason=reason,
        dossier=dossier,
        source="intel",
    )
