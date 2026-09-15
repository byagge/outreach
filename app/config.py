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
