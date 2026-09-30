from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
TEXTS_DIR = DATA_DIR / "texts"
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "outreach.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = ""
    admin_ids: str = ""

    api_id: int = 31999582
    api_hash: str = "d1126aadf79c595b641181fd4d5df2ea"

    timezone: str = "Asia/Bishkek"

    api_key: str = ""
    api_host: str = "127.0.0.1"
    api_port: int = 8091
    api_public_url: str = "https://outreachapi.arix.vu"

    # LLM ОБЯЗАТЕЛЕН для «дорогих контактов» (смысловой разбор постов).
    # Рекомендуем OpenAI / Anthropic / OpenRouter — без локальной Ollama.
    # OpenAI:
    #   LLM_BASE_URL=https://api.openai.com/v1
    #   LLM_MODEL=gpt-4o
    # Anthropic:
    #   LLM_BASE_URL=https://api.anthropic.com
    #   LLM_MODEL=claude-sonnet-4-5
    # OpenRouter:
    #   LLM_BASE_URL=https://openrouter.ai/api/v1
    #   LLM_MODEL=anthropic/claude-sonnet-4
    llm_enabled: bool = True
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    # Сильная модель (качество). mini — только если осознанно экономите.
    llm_model: str = "gpt-4o"
    llm_model_refine: str = ""
    llm_timeout: float = 180.0
    # Маленький батч + полные посты
    llm_batch_size: int = 3
    llm_uncensored: bool = True
    llm_max_posts: int = 50
    premium_score_threshold: int = 70
    premium_chat_min_score: int = 0
    # Deep-scan всех групп, если их ≤ top_k; иначе LLM-rank по ~120 постам
    premium_chat_top_k: int = 80
    premium_scan_all_chats: bool = True
    premium_discover_open: bool = True
    premium_discover_join_max: int = 8
    # Сколько сообщений читать в каждой группе (полный скан)
    premium_messages_per_chat: int = 8000
    premium_max_msgs_per_user: int = 60

    @property
    def admins(self) -> set[int]:
        ids: set[int] = set()
        for part in self.admin_ids.split(","):
            part = part.strip()
            if part.isdigit():
                ids.add(int(part))
        return ids

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    TEXTS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
