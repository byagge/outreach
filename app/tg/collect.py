from __future__ import annotations

from dataclasses import dataclass, field

from telethon import TelegramClient
from telethon.tl.types import User

from app.ai.contacts import Classified
from app.utils.banwords import contains_banword


@dataclass
class CollectResult:
    contacts: list[Classified] = field(default_factory=list)
    banned: list[Classified] = field(default_factory=list)
    banned_reasons: dict[str, str] = field(default_factory=dict)
    skipped: int = 0
    notes: list[str] = field(default_factory=list)
    chat_title: str = ""


def _key(item: Classified) -> tuple[str, str]:
    return item.kind, item.value.lower()


def _add(
    result: CollectResult,
    seen: set[tuple[str, str]],
    item: Classified | None,
    *,
    banwords: list[str],
    text_blob: str = "",
) -> None:
    if not item:
        result.skipped += 1
        return
    key = _key(item)
    if key in seen:
        return
    seen.add(key)
    hit = contains_banword(text_blob or item.raw or item.display or "", banwords)
    if hit:
        result.banned.append(item)
        result.banned_reasons[f"{item.kind}:{item.value}"] = f"banword: {hit}"
        return
    result.contacts.append(item)


async def collect_from_chat(
    client: TelegramClient,
    chat_ref: str,
    *,
    mode: str = "all",
    banwords: list[str] | None = None,
) -> CollectResult:
    """mode: all | writers"""
    words = banwords or []
    result = CollectResult()
    entity = await client.get_entity(chat_ref)
    title = getattr(entity, "title", None) or getattr(entity, "username", None) or chat_ref
    result.chat_title = str(title)
    result.notes.append(f"чат: {title}")
    seen: set[tuple[str, str]] = set()

    if mode == "writers":
        user_msgs: dict[int, list[str]] = {}
        user_map: dict[int, User] = {}
        async for msg in client.iter_messages(entity, limit=15000):
            sender = await msg.get_sender()
            if not isinstance(sender, User) or sender.bot or sender.deleted:
                continue
            user_map[sender.id] = sender
            if msg.message:
                user_msgs.setdefault(sender.id, []).append(msg.message)
        for uid, texts in user_msgs.items():
            user = user_map.get(uid)
            if not user:
                continue
            _add(result, seen, _user_classified(user), banwords=words, text_blob="\n".join(texts))
        result.notes.append(f"режим: писавшие ({len(result.contacts)})")
        return result

    # all participants; banwords from a single message sweep when configured
    banned_ids: set[int] = set()
    if words:
        async for msg in client.iter_messages(entity, limit=8000):
            if not msg.message:
                continue
            hit = contains_banword(msg.message, words)
            if not hit:
                continue
            sender = await msg.get_sender()
            if isinstance(sender, User) and not sender.bot:
                banned_ids.add(sender.id)

    async for user in client.iter_participants(entity):
        if not isinstance(user, User) or user.bot or user.deleted:
            result.skipped += 1
            continue
        item = _user_classified(user)
        if not item:
            result.skipped += 1
            continue
        key = _key(item)
        if key in seen:
            continue
        seen.add(key)
        if user.id in banned_ids:
            result.banned.append(item)
            result.banned_reasons[f"{item.kind}:{item.value}"] = "banword in chat history"
            continue
        result.contacts.append(item)

    result.notes.append(f"режим: все участники ({len(result.contacts)})")
    return result


async def collect_dm_history(
    client: TelegramClient,
    *,
    mode: str = "messaged",
    banwords: list[str] | None = None,
    dialog_limit: int = 500,
) -> CollectResult:
    """
    mode:
      messaged — кому писали (есть исходящее в ЛС)
      replied  — кто отвечал (есть входящее в ЛС)
    """
    words = banwords or []
    result = CollectResult()
    result.notes.append(f"режим ЛС: {mode}")
    seen: set[tuple[str, str]] = set()

    async for dialog in client.iter_dialogs(limit=dialog_limit):
        entity = dialog.entity
        if not isinstance(entity, User) or entity.bot or entity.deleted:
            continue
        texts: list[str] = []
        has_out = False
        has_in = False
        async for msg in client.iter_messages(entity, limit=120):
            if msg.message:
                texts.append(msg.message)
            if msg.out:
                has_out = True
            else:
                has_in = True
            if has_out and has_in:
                break

        if mode == "messaged" and not has_out:
            continue
        if mode == "replied" and not has_in:
            continue

        _add(
            result,
            seen,
            _user_classified(entity),
            banwords=words,
            text_blob="\n".join(texts),
        )

    result.notes.append(f"найдено: {len(result.contacts)}, бан: {len(result.banned)}")
    return result


def _user_classified(user: User) -> Classified | None:
    if user.username:
        return Classified(
            "username",
            user.username.lower(),
            0.95,
            "участник",
            raw=f"@{user.username}",
            display=f"@{user.username}",
        )
    return Classified(
        "user_id",
        str(user.id),
        0.9,
        "без username",
        raw=str(user.id),
        display=str(user.id),
    )
