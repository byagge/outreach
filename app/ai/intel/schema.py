"""Структуры Lead Intelligence."""

from __future__ import annotations

from dataclasses import dataclass, field


# Намерения, которые модель может повесить на поведение в постах
INTENT_LABELS = (
    "hunting_clients",      # ищет клиентов / лиды / заказы на свои услуги
    "selling_offer",        # продаёт услугу/продукт (не код)
    "hiring_ops",           # нанимает чаттеров/МБ/менеджеров/ассистентов
    "hiring_devs",          # нанимает разработчиков
    "ops_scaling",          # слоты, аккаунты, воронки, нагрузка, масштаб
    "deal_negotiation",     # ставки, % , условия, партнёрка
    "coding_work",          # пишет/продаёт код, ботов, скрипты как услугу
    "jobseeking",           # ищет работу как сотрудник
    "noise",                # болтовня без коммерции
)


@dataclass
class PersonRaw:
    """Сырьё с Telegram до анализа."""

    user_id: int
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    bio: str = ""
    posts: list[str] = field(default_factory=list)
    chat_titles: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return " ".join(x for x in [self.first_name, self.last_name] if x).strip()

    def posts_block(self, *, max_posts: int = 60, max_chars: int = 20000) -> str:
        lines: list[str] = []
        used = 0
        for i, p in enumerate(self.posts[:max_posts], 1):
            t = (p or "").strip()
            if not t:
                continue
            line = f"[{i}] {t}"
            if used + len(line) + 1 > max_chars and lines:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines) if lines else "(no posts)"


@dataclass
class PersonDossier:
    """Досье: кто человек по смыслу постов."""

    user_id: int
    role: str = "unknown"  # operator | coder | employee | consumer | unknown
    hypothesis: str = ""  # 1–2 предложения: чем занимается
    intents: dict[str, int] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)  # цитаты/факты из постов
    anti_signals: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class FitVerdict:
    """Вердикт для outreach: bucket + числовой score."""

    bucket: str  # premium | coders | other
    score: int  # 0–100
    reason: str
    dossier: PersonDossier
    source: str = "intel"

    @property
    def extra(self) -> str:
        ev = "; ".join(self.dossier.evidence[:3])
        return (
            f"score={self.score}|{self.bucket}|{self.dossier.role}|"
            f"{self.reason}|{ev}"
        )[:240]


@dataclass
class ChatRank:
    chat_id: int
    title: str
    score: int  # 0–100 стоит ли сканить
    theme: str
    reason: str
