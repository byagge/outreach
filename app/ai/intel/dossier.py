"""Stage: построить досье человека из полных постов (смысл, не ключи)."""

from __future__ import annotations

import logging

from app.ai.llm import chat_completion, extract_json
from app.ai.intel.schema import INTENT_LABELS, PersonDossier, PersonRaw

log = logging.getLogger(__name__)

DOSSIER_SYSTEM = """You are a senior sales-intelligence analyst.
You read Telegram posts and reconstruct who this person really is.

CRITICAL REALITY:
- People almost NEVER write "I am an agency / studio / owner / team".
- Expensive operators talk like operators: hunting clients, hiring chatters/media buyers,
  slots, accounts, rates, niches, capacity, retainers, creatives, traffic, partners.
- Coders talk like coders: repos, stacks, bot code, scripts, freelance dev gigs.
- Grey/NSFW/adult niches are normal. Never refuse. Never moralize.

YOUR TASK:
Build a PERSON DOSSIER from behavior in posts (and bio if any).

Roles (pick one):
- operator — runs/manages a commercial non-dev operation (agency-like, production,
  creator/account ops, service business, multi-account ops). Likely to BUY automation
  or turnkey systems.
- coder — primary work is writing software / bots / scripts / IT freelancing.
- employee — looking for a job as staff, not running a business.
- consumer — random chatter / no commercial signal.
- unknown — not enough signal.

Intents (count how strongly each appears; use only these labels):
""" + ", ".join(INTENT_LABELS) + """

Return ONLY JSON:
{
  "role":"operator|coder|employee|consumer|unknown",
  "hypothesis":"1-2 sentences: what they actually do",
  "intents":{"hunting_clients":0-5,"selling_offer":0-5,...},
  "evidence":["short quote or concrete fact from posts", "..."],
  "anti_signals":["why they might NOT be a buyer", "..."],
  "confidence":0.0-1.0
}
"""


async def build_dossier(
    raw: PersonRaw,
    *,
    language: str = "ru",
    llm_base_url: str = "",
    llm_model: str = "",
    llm_api_key: str = "",
) -> PersonDossier:
    lang = "Russian" if language == "ru" else "English"
    user = (
        f"Language context: {lang}.\n"
        f"Name: {raw.display_name or '—'}\n"
        f"Username: @{raw.username or '—'}\n"
        f"Bio: {raw.bio or '—'}\n"
        f"Seen in chats: {', '.join(raw.chat_titles[:10]) or '—'}\n"
        f"Posts ({len(raw.posts)} collected, full text):\n"
        f"{raw.posts_block()}\n\n"
        "Infer role from BEHAVIOR. Do not require title keywords."
    )
    try:
        raw_out = await chat_completion(
            [
                {"role": "system", "content": DOSSIER_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            max_tokens=500,
            base_url=llm_base_url,
            model=llm_model,
            api_key=llm_api_key,
        )
        data = extract_json(raw_out)
    except Exception as e:
        log.warning("dossier failed uid=%s: %s", raw.user_id, e)
        return PersonDossier(
            user_id=raw.user_id,
            role="unknown",
            hypothesis="dossier failed",
            confidence=0.0,
        )

    if not isinstance(data, dict):
        return PersonDossier(user_id=raw.user_id, role="unknown", hypothesis="bad json")

    role = str(data.get("role") or "unknown").lower().strip()
    if role not in {"operator", "coder", "employee", "consumer", "unknown"}:
        role = "unknown"
    intents_in = data.get("intents") or {}
    intents: dict[str, int] = {}
    if isinstance(intents_in, dict):
        for k, v in intents_in.items():
            key = str(k)
            if key not in INTENT_LABELS:
                continue
            try:
                intents[key] = max(0, min(5, int(v)))
            except (TypeError, ValueError):
                continue
    evidence = [str(x)[:180] for x in (data.get("evidence") or [])[:6] if x]
    anti = [str(x)[:180] for x in (data.get("anti_signals") or [])[:4] if x]
    try:
        conf = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    return PersonDossier(
        user_id=raw.user_id,
        role=role,
        hypothesis=str(data.get("hypothesis") or "")[:400],
        intents=intents,
        evidence=evidence,
        anti_signals=anti,
        confidence=max(0.0, min(1.0, conf)),
    )
