from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Ok(BaseModel):
    ok: bool = True
    detail: str = ""


class SettingsUpdate(BaseModel):
    delay_min: int | None = None
    delay_max: int | None = None
    between_delay_min: int | None = None
    between_delay_max: int | None = None
    typing: bool | None = None
    rotate_proxy_every: int | None = None
    variant_mode: str | None = None
    continuous: bool | None = None


class RawSetting(BaseModel):
    value: str


class AccountCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)


class AccountUpdate(BaseModel):
    label: str | None = None
    assigned: int | None = None
    work_start: str | None = None
    work_end: str | None = None
    delay_min: int | None = None
    delay_max: int | None = None
    status: str | None = None
    last_error: str | None = None
    phone: str | None = None
    username: str | None = None
    user_id: int | None = None


class AccountPause(BaseModel):
    seconds: int = Field(ge=1, le=86400 * 7)
    error: str = ""


class ProxiesAdd(BaseModel):
    text: str = Field(min_length=1, description="Список прокси, по одному на строку")


class ProxyBind(BaseModel):
    account_id: int
    bind: bool = True


class BaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    isolated: int = 0
    enabled: int = 1


class BaseRename(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class BaseAssign(BaseModel):
    campaign_id: int


class BaseFlags(BaseModel):
    isolated: int | None = None
    enabled: int | None = None


class ContactsAdd(BaseModel):
    text: str = Field(min_length=1, description="Контакты текстом")
    base_id: int | None = None


class ContactFinish(BaseModel):
    status: str = Field(description="sent|error|skip|pending")
    account_id: int | None = None
    text_id: int | None = None
    error: str = ""


class TextCreate(BaseModel):
    text: str = ""
    title: str = ""
    entities: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Telegram entities. Premium emoji: "
            '{"type":"custom_emoji","offset":0,"length":2,"custom_emoji_id":"5278…"} '
            "или маркеры в text: {e:5278…}"
        ),
    )
    photo_path: str = ""
    enabled: int = 1
    expand_emoji_markers: bool = Field(
        default=True,
        description="Раскрывать {e:ID} / {{emoji:ID}} в тексте в premium emoji",
    )


class TextUpdate(BaseModel):
    text: str | None = None
    title: str | None = None
    entities: list[dict[str, Any]] | None = None
    entities_json: str | None = None
    photo_path: str | None = None
    enabled: int | None = None
    expand_emoji_markers: bool | None = True


class BlocklistAdd(BaseModel):
    text: str = Field(min_length=1)
    note: str = ""


class BanwordsAdd(BaseModel):
    words: list[str] = Field(min_length=1)


class BanContactAdd(BaseModel):
    kind: str
    value: str
    display: str = ""
    reason: str = ""
    source_base_id: int | None = None


class CollectChatBody(BaseModel):
    chat: str = Field(min_length=1, description="Ссылка/@username чата")
    mode: str = Field(default="all", description="all | writers")
    account_id: int | None = None
    base_name: str | None = None
    isolated: bool = False


class CollectDmBody(BaseModel):
    mode: str = Field(default="messaged", description="messaged | replied")
    account_id: int | None = None
    base_name: str | None = None
    dialog_limit: int = 500
    isolated: bool = False


class CollectPremiumBody(BaseModel):
    language: str = Field(default="ru", description="ru | en")
    account_id: int | None = None
    messages_per_chat: int = Field(default=8000, ge=100, le=20000)
    use_llm: bool | None = None
    discover_open: bool | None = None
    max_discover_join: int = Field(default=8, ge=0, le=30)


class MailingBaseBody(BaseModel):
    name: str = "Итоговая рассылка"
    source_base_id: int | None = None


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class CampaignRename(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class CampaignIdsBody(BaseModel):
    ids: list[int] = Field(default_factory=list)