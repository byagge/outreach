from __future__ import annotations

from dataclasses import dataclass, field

from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, PeerChannel, PeerChat, User

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
    stopped: bool = False


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
    # Банворды только по тексту сообщений, не по @username / user_id
    hit = contains_banword(text_blob, banwords) if text_blob.strip() else None
    if hit:
        result.banned.append(item)
        result.banned_reasons[f"{item.kind}:{item.value}"] = f"banword: {hit}"
        return
    result.contacts.append(item)


def _cancelled(check) -> bool:
    return bool(check and check())


async def resolve_chat_entity(client: TelegramClient, chat_ref: str):
    """
    Резолв публичных и приватных чатов.
    Для -100… / numeric id — ищем в диалогах (нужен access_hash).
    """
    from telethon import utils

    raw = (chat_ref or "").strip()
    if not raw:
        raise ValueError("Пустая ссылка/id чата")

    # 1) username / invite / t.me
    if not raw.lstrip("-").isdigit():
        return await client.get_entity(raw)

    n = int(raw)
    errors: list[str] = []

    # 2) прогреть кэш диалогов (без access_hash приватный id не резолвится)
    try:
        dialogs = await client.get_dialogs(limit=None)
    except Exception as e:
        errors.append(f"dialogs: {e}")
        dialogs = []
        try:
            dialogs = [d async for d in client.iter_dialogs(limit=None)]
        except Exception as e2:
            errors.append(f"iter_dialogs: {e2}")

    bare: set[int] = {abs(n)}
    s = str(n)
    if s.startswith("-100") and len(s) > 4:
        bare.add(int(s[4:]))
    elif n < 0:
        bare.add(-n)

    for d in dialogs:
        try:
            if int(d.id) == n:
                return d.entity
        except Exception:
            pass
        ent = d.entity
        try:
            if utils.get_peer_id(ent) == n:
                return ent
        except Exception:
            pass
        if isinstance(ent, Channel) and ent.id in bare:
            return ent
        if isinstance(ent, Chat) and ent.id in bare:
            return ent
        if isinstance(ent, Channel) and int(f"-100{ent.id}") == n:
            return ent

    # 3) Peer* после прогрева кэша
    candidates: list = [n]
    for b in bare:
        candidates.append(PeerChannel(b))
        candidates.append(PeerChat(b))
    for cand in candidates:
        try:
            return await client.get_entity(cand)
        except Exception as e:
            errors.append(str(e)[:100])

    groups: list[str] = []
    for d in dialogs:
        if isinstance(d.entity, (Channel, Chat)):
            title = (d.name or "?")[:40]
            groups.append(f"{title} ({d.id})")
            if len(groups) >= 10:
                break
    sample = ", ".join(groups) if groups else "в диалогах этого аккаунта нет групп/каналов"
    raise RuntimeError(
        f'Cannot find any entity corresponding to "{raw}". '
        f"Аккаунт должен уже состоять в чате (откройте чат в session и повторите), "
        f"либо пришлите invite/t.me. Доступные: {sample}. "
        f"({'; '.join(errors[-2:])})"
    )


async def collect_from_chat(
    client: TelegramClient,
    chat_ref: str,
    *,
    mode: str = "all",
    banwords: list[str] | None = None,
    should_stop=None,
    on_progress=None,
) -> CollectResult:
    """mode: all | writers. should_stop() -> bool для кнопки Стоп."""
    words = banwords or []
    result = CollectResult()
    entity = await resolve_chat_entity(client, chat_ref)
    title = getattr(entity, "title", None) or getattr(entity, "username", None) or str(chat_ref)
    result.chat_title = str(title)
    result.notes.append(f"чат: {title}")
    seen: set[tuple[str, str]] = set()

    async def _progress(msg: str) -> None:
        if on_progress:
            await on_progress(msg)

    if mode == "writers":
        user_msgs: dict[int, list[str]] = {}
        user_map: dict[int, User] = {}
        n = 0
        async for msg in client.iter_messages(entity, limit=15000):
            if _cancelled(should_stop):
                result.stopped = True
                break
            n += 1
            if n % 500 == 0:
                await _progress(f"сообщений {n}, юзеров {len(user_map)}")
            sender = await msg.get_sender()
            if not isinstance(sender, User) or sender.bot or sender.deleted:
                continue
            user_map[sender.id] = sender
            if msg.message:
                user_msgs.setdefault(sender.id, []).append(msg.message)
        for uid, texts in user_msgs.items():
            if _cancelled(should_stop):
                result.stopped = True
                break
            user = user_map.get(uid)
            if not user:
                continue
            # каждое сообщение отдельно — не склеиваем в один супер-текст
            hit_word: str | None = None
            for msg_text in texts:
                hit_word = contains_banword(msg_text, words)
                if hit_word:
                    break
            item = _user_classified(user)
            if not item:
                continue
            key = _key(item)
            if key in seen:
                continue
            seen.add(key)
            if hit_word:
                result.banned.append(item)
                result.banned_reasons[f"{item.kind}:{item.value}"] = f"banword: {hit_word}"
            else:
                result.contacts.append(item)
        tag = "остановлено" if result.stopped else "готово"
        result.notes.append(f"режим: писавшие ({len(result.contacts)}) [{tag}]")
        return result

    banned_ids: dict[int, str] = {}
    if words:
        n = 0
        async for msg in client.iter_messages(entity, limit=8000):
            if _cancelled(should_stop):
                result.stopped = True
                break
            n += 1
            if not msg.message:
                continue
            hit = contains_banword(msg.message, words)
            if not hit:
                continue
            sender = await msg.get_sender()
            if isinstance(sender, User) and not sender.bot:
                banned_ids.setdefault(sender.id, hit)

    n = 0
    async for user in client.iter_participants(entity):
        if _cancelled(should_stop):
            result.stopped = True
            break
        n += 1
        if n % 200 == 0:
            await _progress(f"участников {n}, в базе {len(result.contacts)}")
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
            result.banned_reasons[f"{item.kind}:{item.value}"] = (
                f"banword: {banned_ids[user.id]}"
            )
            continue
        result.contacts.append(item)

    tag = "остановлено" if result.stopped else "готово"
    result.notes.append(f"режим: все участники ({len(result.contacts)}) [{tag}]")
    return result


async def collect_dm_history(
    client: TelegramClient,
    *,
    mode: str = "messaged",
    banwords: list[str] | None = None,
    dialog_limit: int = 500,
    should_stop=None,
) -> CollectResult:
    words = banwords or []
    result = CollectResult()
    result.notes.append(f"режим ЛС: {mode}")
    seen: set[tuple[str, str]] = set()

    async for dialog in client.iter_dialogs(limit=dialog_limit):
        if _cancelled(should_stop):
            result.stopped = True
            break
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
