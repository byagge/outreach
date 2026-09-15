from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Account:
    id: int
    label: str
    phone: str = ""
    username: str = ""
    user_id: int | None = None
    telethon_session: str = ""
    proxy_cursor: int = 0
    assigned: int = 1
    status: str = "idle"
    last_error: str = ""
    pause_until: str = ""
    sent_count: int = 0
    work_start: str = ""
    work_end: str = ""
    delay_min: int | None = None
    delay_max: int | None = None
    created_at: str = ""
    updated_at: str = ""

    @property
    def display(self) -> str:
        uname = f"@{self.username}" if self.username else (self.phone or f"id={self.id}")
        return f"{self.label} ({uname})"

    @property
    def has_telethon(self) -> bool:
        return bool(self.telethon_session)


@dataclass
class Proxy:
    id: int
    raw: str
    scheme: str = "socks5"
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    status: str = "ok"
    last_error: str = ""
    created_at: str = ""

    @property
    def label(self) -> str:
        auth = f"{self.username}@" if self.username else ""
        return f"{self.scheme}://{auth}{self.host}:{self.port}"


@dataclass
class ContactBase:
    id: int
    name: str
    enabled: int = 1
    created_at: str = ""

    @property
    def on(self) -> bool:
        return bool(self.enabled)


@dataclass
class Contact:
    id: int
    raw: str
    kind: str
    value: str
    display: str = ""
    extra: str = ""
    status: str = "pending"
    last_error: str = ""
    sent_at: str = ""
    account_id: int | None = None
    text_id: int | None = None
    base_id: int | None = None
    created_at: str = ""

    @property
    def pretty(self) -> str:
        if self.kind == "username":
            v = self.value if self.value.startswith("@") else f"@{self.value}"
            return v
        if self.kind == "phone":
            return self.value if self.value.startswith("+") else f"+{self.value.lstrip('+')}"
        if self.kind == "user_id":
            return self.value
        return self.raw or self.value or "—"


@dataclass
class TextVariant:
    id: int
    title: str = ""
    text: str = ""
    entities_json: str = "[]"
    photo_path: str = ""
    enabled: int = 1
    created_at: str = ""


@dataclass
class SendRow:
    id: int
    contact_id: int | None
    account_id: int | None
    text_id: int | None
    proxy_id: int | None
    status: str
    detail: str = ""
    created_at: str = ""
    contact_pretty: str = ""
    account_label: str = ""


@dataclass
class Job:
    id: int
    account_id: int | None
    kind: str
    status: str
    started_at: str = ""
    finished_at: str = ""
    report: str = ""
    account_label: str = ""


@dataclass
class JobLog:
    id: int
    job_id: int
    created_at: str
    level: str
    message: str


@dataclass
class BlockEntry:
    id: int
    kind: str
    value: str
    note: str = ""
    created_at: str = ""

    @property
    def pretty(self) -> str:
        if self.kind == "username":
            v = self.value if self.value.startswith("@") else f"@{self.value}"
            return v
        return self.value


@dataclass
class BanContact:
    id: int
    kind: str
    value: str
    display: str = ""
    reason: str = ""
    source_base_id: int | None = None
    created_at: str = ""

    @property
    def pretty(self) -> str:
        if self.kind == "username":
            v = self.value if self.value.startswith("@") else f"@{self.value}"
            return v
        return self.display or self.value


@dataclass
class CollectRun:
    id: int
    source: str = "bot"  # bot | api
    kind: str = ""  # chat | dm | mailing
    mode: str = ""
    target: str = ""
    title: str = ""
    account_id: int | None = None
    base_id: int | None = None
    added: int = 0
    banned: int = 0
    stopped: int = 0
    notes: str = ""
    created_at: str = ""
    account_label: str = ""
    base_name: str = ""

    @property
    def label(self) -> str:
        bit = self.title or self.target or self.mode or self.kind
        src = "API" if self.source == "api" else "бот"
        return f"{src} · {bit}"


@dataclass
class OutreachSettings:
    delay_min: int = 60
    delay_max: int = 120
    between_delay_min: int = 0
    between_delay_max: int = 0
    typing: bool = True
    rotate_proxy_every: int = 1
    variant_mode: str = "random"
    continuous: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Counts:
    accounts: int = 0
    assigned: int = 0
    proxies: int = 0
    contacts: int = 0
    pending: int = 0
    sent: int = 0
    errors: int = 0
    skipped: int = 0
    texts: int = 0
    bases: int = 0
    bases_enabled: int = 0
    blocklist: int = 0
    banwords: int = 0
    ban_contacts: int = 0
