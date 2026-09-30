"""
Lead Intelligence — система сбора дорогих клиентов для outreach.

Качество > ложная экономия:
  • полный deep-scan групп (тысячи сообщений)
  • полные тексты постов в сильную модель
  • 1 вызов = досье + score по поведению (не слова agency/студия)
  • экономия только: мусор «ок/лол», точные дубли, пустые профили
"""

from __future__ import annotations

from app.ai.intel.pipeline import IntelConfig, run_people_intelligence, run_person_intelligence
from app.ai.intel.schema import ChatRank, FitVerdict, PersonDossier

__all__ = [
    "ChatRank",
    "FitVerdict",
    "IntelConfig",
    "PersonDossier",
    "run_people_intelligence",
    "run_person_intelligence",
]
