"""Бесплатный локальный triage — отсекает до LLM (0 токенов)."""

from __future__ import annotations

import re

from app.ai.intel.schema import FitVerdict, PersonDossier, PersonRaw

_CODER = re.compile(
    r"(?i)("
    r"github\.com|gitlab\.com|npm install|pull request|leetcode|"
    r"пишу\s*(на\s*)?(python|javascript|typescript|golang|react)|"
    r"fullstack|software engineer|разработаю\s*(бота|сайт|парсер)|"
    r"заказ\s*на\s*(бота|парс|сайт|скрипт)"
    r")"
)
_JOB = re.compile(
    r"(?i)(ищу\s*работ[уы]|looking for a job|резюме|\bcv\b|я студент|open to work)"
)
_EMPTYISH = re.compile(r"^[\W\d_]{0,8}$")


def triage_local(raw: PersonRaw) -> FitVerdict | None:
    """
    None = нужен LLM.
    FitVerdict = решение без LLM.
    """
    text = "\n".join(raw.posts[:30]) + "\n" + (raw.bio or "")
    substantive = [p for p in raw.posts if p and len(p.strip()) >= 12 and not _EMPTYISH.match(p.strip())]

    if len(substantive) < 2 and not (raw.bio and len(raw.bio) > 20):
        d = PersonDossier(raw.user_id, "unknown", "мало текста", confidence=0.9)
        return FitVerdict("other", 8, "мало сигнала — skip LLM", d, source="triage")

    if _CODER.search(text):
        d = PersonDossier(raw.user_id, "coder", "явный код", confidence=0.85)
        return FitVerdict("coders", 22, "local: coder markers", d, source="triage")

    if _JOB.search(text) and not re.search(r"(?i)(нанима|hire|ищу\s*клиент)", text):
        d = PersonDossier(raw.user_id, "employee", "jobseeker", confidence=0.8)
        return FitVerdict("other", 12, "local: jobseeker", d, source="triage")

    return None
