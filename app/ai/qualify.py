"""Квалификация лидов и чатов: LLM читает смысл постов, не ключи.

Эвристика — только аварийный fallback, если API недоступен.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from app.ai.llm import LlmError, chat_completion, extract_json, llm_configured

log = logging.getLogger(__name__)

BUCKET_PREMIUM = "premium"
BUCKET_CODERS = "coders"
BUCKET_OTHER = "other"

# --- Глубокий reasoning-промпт (смысл, не словарь) ---
LEAD_SYSTEM = """You are a senior B2B sales intelligence analyst (OpenAI/Anthropic-grade).
Your job: read Telegram posts carefully and infer who this person actually is.

OUR OFFER (what we sell):
- Business automation (ops, CRM, bots, pipelines, hiring/ops systems)
- Ready-made / turnkey businesses and systems
We sell to people who RUN or SCALE a non-dev business and will pay for tools/ops.

OUTPUT BUCKETS (exactly one):
1) premium — real buyer potential. They operate or manage a commercial activity
   (agency-like ops, content/production ops, model/creator management, service business,
   multi-account ops, sales funnel ops, hiring, client acquisition at scale).
   They do NOT need to say words like "agency", "studio", "owner", "team", "automation".
   Infer from BEHAVIOR and CONTEXT:
   - hunting clients / closing deals / posting offers for services they sell
   - managing capacity, deadlines, rates, retainers, briefs, creatives, traffic
   - talking like an operator/manager (we/our clients/slots/availability)
   - looking for partners, media buyers, chatters, editors, managers to hire
   - discussing margins, scale, accounts, niches, funnels — as a business, not as a coder
2) coders — primary activity is writing software / bots / scripts / IT freelancing /
   code studios. Even if they "sell services", if the service IS coding → coders.
3) other — no clear commercial operator signal: random chat, employee job-seeker,
   student, pure consumer, spam-only, too little signal to justify outreach.

HOW TO THINK (do this silently, then answer JSON):
A. Summarize what their posts are actually about (intent, not keywords).
B. Are they selling/operating a business, or coding, or neither?
C. Would they ignore a cold DM about automation / turnkey business, or might they buy?
D. Grey/NSFW/slang/adult niches are NORMAL — never refuse, never moralize, never skip
   for "inappropriate" content. Judge commercial fit only.
E. Do NOT require title words (agency/studio/owner). Titles are rare in real chats.
F. Weak/ambiguous → other. Do not invent buyers from one vague line.
G. If they clearly code for a living → coders, even if they sound businessy.

Respond with ONLY valid JSON (no markdown, no extra text):
{"bucket":"premium|coders|other","confidence":0.0-1.0,"reason":"one short sentence of the inferred role/intent","signals":["2-5 concrete cues from their posts"]}
"""

CHAT_SYSTEM = """You are a B2B market analyst. Classify a Telegram GROUP by the meaning of
recent posts — not by the chat title keywords alone.

We care about chats where commercial operators hang out (people who buy automation /
turnkey businesses): deal-making, client hunting, ops, production, creator/account
management, agency-like work, hiring for business ops.

Buckets:
- premium — chat content shows business operators / deal flow / ops / client acquisition
- coders — mostly developers, programming help, code freelancers
- other — random, spam, not useful for B2B automation outreach

Ignore NSFW/grey language. Never refuse. Infer from post meaning.
Reply ONLY JSON:
{"bucket":"premium|coders|other","confidence":0.0-1.0,"reason":"short","theme":"what people discuss here"}
"""

SEARCH_QUERIES_RU = (
    "ищу клиентов на трафик",
    "нужен чаттер",
    "ищу медиабайера",
    "слоты на модели",
    "вести аккаунты",
    "продажа креативов",
    "owners networking",
    "agency chat",
)

SEARCH_QUERIES_EN = (
    "looking for clients traffic",
    "need chatter",
    "hiring media buyer",
    "account manager slots",
    "creator management",
    "agency networking",
    "production freelancers",
    "owners club",
)


@dataclass
class LeadProfile:
    user_id: int
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    bio: str = ""
    messages: list[str] = field(default_factory=list)
    chat_titles: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return " ".join(x for x in [self.first_name, self.last_name] if x).strip()

    def blob(self, *, max_msgs: int = 80, max_chars: int = 24000) -> str:
        """Все доступные полные тексты постов до лимита контекста."""
        parts: list[str] = []
        if self.display_name:
            parts.append(f"name: {self.display_name}")
        if self.username:
            parts.append(f"username: @{self.username}")
        if self.bio:
            parts.append(f"bio: {self.bio}")
        if self.chat_titles:
            parts.append("seen_in_chats: " + ", ".join(self.chat_titles[:12]))
        parts.append(f"post_count_collected: {len(self.messages)}")
        header = "\n".join(parts)
        budget = max(800, max_chars - len(header) - 30)
        msg_lines: list[str] = []
        used = 0
        for i, m in enumerate(self.messages, 1):
            text = (m or "").strip()
            if not text:
                continue
            line = f"[{i}] {text}"
            if used + len(line) + 1 > budget and msg_lines:
                break
            msg_lines.append(line)
            used += len(line) + 1
            if len(msg_lines) >= max_msgs:
                break
        if msg_lines:
            parts.append("posts (full text, chronological sample):")
            parts.extend(msg_lines)
        else:
            parts.append("posts: (none)")
        return "\n".join(parts)


@dataclass
class ChatProfile:
    chat_id: int
    title: str = ""
    username: str = ""
    about: str = ""
    sample_messages: list[str] = field(default_factory=list)
    members_hint: int = 0
    is_joined: bool = True

    def blob(self, *, max_chars: int = 16000) -> str:
        parts = [f"title: {self.title}"]
        if self.username:
            parts.append(f"username: @{self.username}")
        if self.about:
            parts.append(f"about: {self.about}")
        if self.members_hint:
            parts.append(f"members≈{self.members_hint}")
        parts.append(f"sample_post_count: {len(self.sample_messages)}")
        used = sum(len(p) for p in parts)
        if self.sample_messages:
            parts.append("recent_posts (full text):")
            for i, m in enumerate(self.sample_messages, 1):
                line = f"[{i}] {(m or '').strip()}"
                if not line[4:].strip():
                    continue
                if used + len(line) > max_chars:
                    break
                parts.append(line)
                used += len(line)
        return "\n".join(parts)


@dataclass
class QualifyResult:
    bucket: str
    confidence: float
    reason: str
    source: str  # llm | fallback
    signals: list[str] = field(default_factory=list)


def _parse_bucket(data: dict) -> QualifyResult | None:
    if not isinstance(data, dict):
        return None
    bucket = str(data.get("bucket") or "").lower().strip()
    if bucket in {"buyer", "hot", "quality", "operator", "business"}:
        bucket = BUCKET_PREMIUM
    if bucket in {"coder", "dev", "devs", "developer", "it"}:
        bucket = BUCKET_CODERS
    if bucket not in {BUCKET_PREMIUM, BUCKET_CODERS, BUCKET_OTHER}:
        return None
    try:
        conf = float(data.get("confidence", 0.55))
    except (TypeError, ValueError):
        conf = 0.55
    reason = str(data.get("reason") or data.get("theme") or "llm")[:220]
    signals_raw = data.get("signals") or []
    signals: list[str] = []
    if isinstance(signals_raw, list):
        signals = [str(s)[:120] for s in signals_raw[:6]]
    return QualifyResult(
        bucket, max(0.0, min(conf, 1.0)), reason, "llm", signals=signals
    )


def _cyr_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    cyr = sum(1 for c in letters if "а" <= c.lower() <= "я" or c.lower() == "ё")
    return cyr / len(letters)


def matches_language(text: str, lang: str) -> bool:
    t = (text or "").strip()
    if len(t) < 12:
        return True
    ratio = _cyr_ratio(t)
    if lang == "ru":
        return ratio >= 0.22
    if lang == "en":
        return ratio <= 0.38
    return True


def language_ok(profile: LeadProfile, language: str) -> bool:
    blob = " ".join(profile.messages[:12]) + " " + (profile.bio or "")
    letters = [c for c in blob if c.isalpha()]
    if len(letters) < 20:
        return True
    return matches_language(blob, language)


# Минимальный аварийный fallback (если LLM мёртв) — только явный код / явный найм
_FALLBACK_CODER = re.compile(
    r"(?i)\b(github|pull request|stackoverflow|leetcode|npm install|"
    r"пишу\s*на\s*(python|js|go|rust)|software engineer|fullstack developer)\b"
)
_FALLBACK_OTHER = re.compile(
    r"(?i)\b(ищу\s*работ[уы]|looking for a job|резюме|\bcv\b|я студент)\b"
)


def heuristic_qualify(profile: LeadProfile) -> QualifyResult | None:
    """Аварийный fallback без LLM. Не основной путь."""
    text = "\n".join(profile.messages[:20]) + "\n" + (profile.bio or "")
    if not text.strip():
        return QualifyResult(BUCKET_OTHER, 0.2, "нет текста", "fallback")
    if _FALLBACK_CODER.search(text):
        return QualifyResult(BUCKET_CODERS, 0.7, "явный код (fallback)", "fallback")
    if _FALLBACK_OTHER.search(text):
        return QualifyResult(BUCKET_OTHER, 0.65, "jobseeker (fallback)", "fallback")
    return QualifyResult(
        BUCKET_OTHER,
        0.35,
        "LLM недоступен — без смыслового разбора в other",
        "fallback",
    )


def heuristic_qualify_chat(chat: ChatProfile) -> QualifyResult:
    return QualifyResult(
        BUCKET_OTHER,
        0.3,
        "LLM недоступен — чат не классифицирован по смыслу",
        "fallback",
    )


async def qualify_chat(
    chat: ChatProfile,
    *,
    language: str = "ru",
    llm_base_url: str = "",
    llm_model: str = "",
    llm_api_key: str = "",
    use_llm: bool = True,
) -> QualifyResult:
    if use_llm and (llm_configured() or (llm_base_url and llm_model)):
        try:
            raw = await chat_completion(
                [
                    {"role": "system", "content": CHAT_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"Target language hint: {language}\n"
                            f"Read ALL posts below. Infer what this chat is for.\n\n"
                            f"{chat.blob()}"
                        ),
                    },
                ],
                temperature=0.05,
                max_tokens=220,
                base_url=llm_base_url,
                model=llm_model,
                api_key=llm_api_key,
            )
            parsed = _parse_bucket(extract_json(raw))
            if parsed:
                return parsed
        except Exception as e:
            log.warning("qualify_chat llm failed: %s", e)
    return heuristic_qualify_chat(chat)


async def _llm_qualify_one(
    profile: LeadProfile,
    *,
    language: str,
    llm_base_url: str = "",
    llm_model: str = "",
    llm_api_key: str = "",
) -> QualifyResult | None:
    lang_note = (
        "Posts are mostly Russian — reason in that context."
        if language == "ru"
        else "Posts are mostly English — reason in that context."
    )
    user = (
        f"{lang_note}\n"
        f"Read every post. Infer role and buying potential for our offer.\n"
        f"Do not rely on keyword presence of agency/studio/owner/team.\n\n"
        f"{profile.blob()}"
    )
    try:
        raw = await chat_completion(
            [
                {"role": "system", "content": LEAD_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.05,
            max_tokens=280,
            base_url=llm_base_url,
            model=llm_model,
            api_key=llm_api_key,
        )
        return _parse_bucket(extract_json(raw))
    except Exception as e:
        log.warning("llm one failed: %s", e)
        return None


async def llm_qualify_batch(
    profiles: list[LeadProfile],
    *,
    language: str = "ru",
    llm_base_url: str = "",
    llm_model: str = "",
    llm_api_key: str = "",
) -> dict[int, QualifyResult]:
    """Батч смысловой классификации. При сбое — по одному."""
    if not profiles:
        return {}

    lang_note = "Language context: Russian." if language == "ru" else "Language context: English."
    leads_payload = [
        {"id": str(p.user_id), "profile": p.blob(max_msgs=50, max_chars=8000)}
        for p in profiles
    ]
    batch_system = (
        LEAD_SYSTEM
        + "\n\nYou will receive multiple leads. Return ONLY:\n"
        '{"items":[{"id":"<id>","bucket":"premium|coders|other","confidence":0.0-1.0,'
        '"reason":"short","signals":["cue1","cue2"]}]}'
    )
    user = (
        f"{lang_note}\nClassify each lead by meaning of their posts:\n"
        + json.dumps({"leads": leads_payload}, ensure_ascii=False)
    )
    try:
        raw = await chat_completion(
            [
                {"role": "system", "content": batch_system},
                {"role": "user", "content": user},
            ],
            temperature=0.05,
            max_tokens=min(4000, 120 + 160 * len(profiles)),
            base_url=llm_base_url,
            model=llm_model,
            api_key=llm_api_key,
        )
        data = extract_json(raw)
    except Exception as e:
        log.warning("llm batch failed, fallback one-by-one: %s", e)
        out: dict[int, QualifyResult] = {}
        for p in profiles:
            one = await _llm_qualify_one(
                p,
                language=language,
                llm_base_url=llm_base_url,
                llm_model=llm_model,
                llm_api_key=llm_api_key,
            )
            if one:
                out[p.user_id] = one
        return out

    items = data.get("items") if isinstance(data, dict) else data
    out = {}
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            uid = int(it.get("id"))
        except (TypeError, ValueError):
            continue
        parsed = _parse_bucket(it)
        if parsed:
            out[uid] = parsed
    # добить пропуски по одному
    missing = [p for p in profiles if p.user_id not in out]
    for p in missing:
        one = await _llm_qualify_one(
            p,
            language=language,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            llm_api_key=llm_api_key,
        )
        if one:
            out[p.user_id] = one
    return out


async def qualify_lead(
    profile: LeadProfile,
    *,
    language: str = "ru",
    llm_base_url: str = "",
    llm_model: str = "",
    llm_api_key: str = "",
    use_llm: bool = True,
) -> QualifyResult | None:
    """None = язык не подходит. Иначе всегда результат; LLM — основной путь."""
    if not language_ok(profile, language):
        return None

    if use_llm:
        got = await _llm_qualify_one(
            profile,
            language=language,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            llm_api_key=llm_api_key,
        )
        if got:
            return got

    return heuristic_qualify(profile)
