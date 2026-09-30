"""Оркестратор: качество > ложная экономия."""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.intel.qualify_quality import qualify_batch_quality
from app.ai.intel.schema import FitVerdict, PersonDossier, PersonRaw


@dataclass
class IntelConfig:
    language: str = "ru"
    premium_threshold: int = 70
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_model_refine: str = ""  # unused in quality mode (kept for compat)
    chat_min_score: int = 0
    chat_top_k: int = 80  # deep-scan до стольких групп; все если меньше
    batch_size: int = 3  # маленькие батчи с ПОЛНЫМИ постами
    max_posts_to_llm: int = 50
    refine_lo: int = 0
    refine_hi: int = 0
    enable_refine: bool = False
    scan_all_chats: bool = True  # не выходить после 10–20 сообщений / не резать чаты


@dataclass
class IntelStats:
    triage_skipped: int = 0
    llm_batches: int = 0
    llm_people: int = 0
    refined: int = 0
    approx_input_chars: int = 0


def _empty_verdict(uid: int) -> FitVerdict:
    return FitVerdict(
        "other",
        5,
        "нет постов",
        PersonDossier(uid, "unknown", "no posts"),
        source="triage",
    )


async def run_people_intelligence(
    people: list[PersonRaw],
    cfg: IntelConfig,
    *,
    should_stop=None,
    on_progress=None,
) -> tuple[dict[int, FitVerdict], IntelStats]:
    """
    Quality path:
      skip only empty → full posts → strong model (1 call = dossier+score)
      small batches (2–3) keep quality; fallback one-by-one on miss
    """
    stats = IntelStats()
    out: dict[int, FitVerdict] = {}
    queue: list[PersonRaw] = []

    for raw in people:
        substantive = [p for p in raw.posts if p and len(p.strip()) >= 8]
        if len(substantive) < 2 and not (raw.bio and len(raw.bio) > 25):
            out[raw.user_id] = _empty_verdict(raw.user_id)
            stats.triage_skipped += 1
            continue
        queue.append(raw)

    bs = max(1, min(4, int(cfg.batch_size or 3)))
    total = len(queue)
    for i in range(0, total, bs):
        if should_stop and should_stop():
            break
        chunk = queue[i : i + bs]
        if on_progress:
            await on_progress(f"LLM quality {min(i + bs, total)}/{total}")
        from app.ai.intel.prepare import person_prompt_block

        for p in chunk:
            stats.approx_input_chars += len(person_prompt_block(p, max_posts=cfg.max_posts_to_llm))

        got = await qualify_batch_quality(
            chunk,
            language=cfg.language,
            premium_threshold=cfg.premium_threshold,
            llm_base_url=cfg.llm_base_url,
            llm_model=cfg.llm_model,
            llm_api_key=cfg.llm_api_key,
            max_posts=cfg.max_posts_to_llm,
        )
        stats.llm_batches += 1
        stats.llm_people += len(chunk)
        out.update(got)

    return out, stats


async def run_person_intelligence(raw: PersonRaw, cfg: IntelConfig) -> FitVerdict:
    got, _ = await run_people_intelligence([raw], cfg)
    return got.get(raw.user_id) or _empty_verdict(raw.user_id)
