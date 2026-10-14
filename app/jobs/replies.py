"""
Приём ответов на рассылку.

Раз в reply_poll_sec секунд для каждого аккаунта читаем свежие диалоги и ищем в них
входящие от тех, кому мы писали. Сообщение со ссылкой — это редирект/реклама, а не ответ:
оно сохраняется (valid=0, для статистики «редиректы»), но не считается ответом и
не уведомляет.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from datetime import timezone
from typing import Any

from telethon.tl.types import User

from app.models import Account, Reply, ReplyAnswer
from app.store import Store
from app.tg.client import account_lock, telethon_client
from app.tg.send import resolve_peer
from app.utils.entities import to_telethon_entities
from app.utils.links import has_link

log = logging.getLogger("outreach.replies")

Notify = Callable[[Reply], Awaitable[None]]

DEFAULT_POLL_SEC = 45
LOCK_WAIT_SEC = 60.0
FAIL_BACKOFF_SEC = 600.0


class AnswerError(RuntimeError):
    pass


# ---------------------------------------------------------------- helpers


def media_kind(msg: Any) -> str:
    """Короткая пометка вложения для сообщений без текста."""
    try:
        if getattr(msg, "sticker", None):
            return "стикер"
        if getattr(msg, "voice", None):
            return "голосовое"
        if getattr(msg, "video_note", None):
            return "кружок"
        if getattr(msg, "gif", None):
            return "gif"
        if getattr(msg, "photo", None):
            return "фото"
        if getattr(msg, "video", None):
            return "видео"
        if getattr(msg, "audio", None):
            return "аудио"
        if getattr(msg, "document", None):
            return "файл"
        if getattr(msg, "contact", None):
            return "контакт"
        if getattr(msg, "geo", None):
            return "геопозиция"
        if getattr(msg, "poll", None):
            return "опрос"
    except Exception:
        pass
    return ""


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


class ContactIndex:
    """Поиск «наш ли это получатель» по peer_id / username / телефону."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.by_peer: dict[int, dict[str, Any]] = {}
        self.by_username: dict[str, dict[str, Any]] = {}
        self.by_phone: dict[str, dict[str, Any]] = {}
        for r in rows:
            peer = r.get("peer_id")
            if peer:
                self.by_peer[int(peer)] = r
            kind, value = r.get("kind"), (r.get("value") or "").strip()
            if kind == "user_id" and value.lstrip("-").isdigit():
                self.by_peer.setdefault(int(value), r)
            elif kind == "username" and value:
                self.by_username[value.lstrip("@").lower()] = r
            elif kind == "phone" and value:
                self.by_phone[_digits(value)] = r

    def __bool__(self) -> bool:
        return bool(self.by_peer or self.by_username or self.by_phone)

    def match(self, user: User) -> dict[str, Any] | None:
        hit = self.by_peer.get(int(user.id))
        if hit:
            return hit
        names = {(getattr(user, "username", "") or "").lower()}
        for u in getattr(user, "usernames", None) or []:
            names.add((getattr(u, "username", "") or "").lower())
        names.discard("")
        for n in names:
            if n in self.by_username:
                return self.by_username[n]
        phone = _digits(getattr(user, "phone", "") or "")
        if phone and phone in self.by_phone:
            return self.by_phone[phone]
        return None


def _iso(dt) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _full_name(user: User) -> str:
    return " ".join(p for p in (user.first_name, user.last_name) if p).strip()


# ---------------------------------------------------------------- polling

# (account_id, peer_id) -> id верхнего сообщения диалога, которое уже обработали
_seen_top: dict[tuple[int, int], int] = {}
_fail_until: dict[int, float] = {}


async def poll_account(
    store: Store,
    acc: Account,
    *,
    client=None,
    dialogs_limit: int = 300,
) -> list[Reply]:
    """
    Один проход по аккаунту. Возвращает ТОЛЬКО новые валидные ответы, по которым
    ещё надо уведомить. Если client не передан — подключается сам.
    """
    idx = ContactIndex(await store.reply_contact_index(acc.id))
    if not idx:
        return []

    if client is None:
        proxy = await store.peek_proxy(acc.id)
        try:
            await asyncio.wait_for(account_lock(acc.id).acquire(), LOCK_WAIT_SEC)
        except asyncio.TimeoutError:
            return []
        try:
            async with telethon_client(acc.telethon_session, proxy) as c:
                return await _scan(store, acc, c, idx, dialogs_limit)
        finally:
            account_lock(acc.id).release()
    return await _scan(store, acc, client, idx, dialogs_limit)


async def _scan(store: Store, acc: Account, client, idx: ContactIndex, limit: int) -> list[Reply]:
    since = await store.replies_tracking_since()
    fresh: list[Reply] = []
    async for dialog in client.iter_dialogs(limit=limit, ignore_migrated=True):
        user = dialog.entity
        if not isinstance(user, User) or user.bot or getattr(user, "is_self", False):
            continue
        ref = idx.match(user)
        if not ref:
            continue
        top = getattr(dialog.message, "id", 0) or 0
        key = (acc.id, int(user.id))
        if top and _seen_top.get(key, 0) >= top:
            continue
        if not ref.get("peer_id") and ref.get("contact_id"):
            await store.link_send_peer(acc.id, ref["contact_id"], int(user.id))
            ref["peer_id"] = int(user.id)

        min_id = int(ref.get("message_id") or 0)
        msgs = await client.get_messages(user, limit=40, min_id=min_id)
        sent_at = ref.get("sent_at") or ""
        for m in sorted(msgs, key=lambda x: x.id):
            if getattr(m, "out", False) or getattr(m, "action", None):
                continue
            msg_date = _iso(m.date)
            if sent_at and msg_date < sent_at[:19]:
                continue  # писал нам до нашего оффера — не ответ
            text = (m.raw_text or "").strip()
            media = media_kind(m)
            if not text and not media:
                continue
            link = has_link(
                text,
                list(getattr(m, "entities", None) or []),
                web_preview=bool(getattr(m, "web_preview", None)),
            )
            reply = await store.add_reply(
                account_id=acc.id,
                peer_id=int(user.id),
                tg_msg_id=int(m.id),
                contact_id=ref.get("contact_id"),
                send_id=ref.get("send_id"),
                text_id=ref.get("text_id"),
                campaign_id=ref.get("campaign_id"),
                campaign_name=ref.get("campaign_name") or "",
                text=text,
                media=media,
                from_name=_full_name(user),
                from_username=getattr(user, "username", "") or "",
                has_link=link,
                msg_date=msg_date,
                notified=bool(since and msg_date < since[:19]),  # бэкфилл — без шума
            )
            if reply and reply.valid and not reply.notified:
                fresh.append(reply)
        if top:
            _seen_top[key] = top
    return fresh


async def poll_all(store: Store, notify: Notify | None) -> int:
    """Опросить все аккаунты с session и разослать накопленные уведомления."""
    for acc in await store.list_accounts():
        if not acc.telethon_session:
            continue
        if _fail_until.get(acc.id, 0) > time.monotonic():
            continue
        try:
            await poll_account(store, acc)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # сеть/прокси/мёртвая session — не роняем весь цикл
            log.warning("reply poll %s failed: %s", acc.label, e)
            _fail_until[acc.id] = time.monotonic() + FAIL_BACKOFF_SEC
            continue
        await asyncio.sleep(1.0)
    return await flush_notifications(store, notify)


async def flush_notifications(store: Store, notify: Notify | None) -> int:
    """
    Отправить уведомления по всем ненотифицированным ответам. Если отправка не удалась
    (нет чата, Telegram недоступен) — ответ остаётся в очереди до следующего цикла.
    """
    sent = 0
    for reply in await store.pending_notifications():
        if notify is None:
            await store.mark_reply_notified(reply.id)
            continue
        try:
            await notify(reply)
        except Exception:
            log.exception("reply notify failed (retry next cycle)")
            break
        await store.mark_reply_notified(reply.id)
        sent += 1
    return sent


async def run_reply_listener(store: Store, notify: Notify | None) -> None:
    log.info("reply listener started")
    while True:
        try:
            if (await store.get_setting("reply_listener", "1")) != "0":
                await poll_all(store, notify)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("reply listener iteration failed")
        raw = await store.get_setting("reply_poll_sec", str(DEFAULT_POLL_SEC))
        try:
            interval = min(600, max(15, int(raw)))
        except ValueError:
            interval = DEFAULT_POLL_SEC
        await asyncio.sleep(interval)


# ---------------------------------------------------------------- answers


async def send_answer(
    store: Store,
    reply_id: int,
    text: str,
    entities: list[dict] | None = None,
    *,
    source: str = "bot",
) -> ReplyAnswer:
    """Написать человеку с того же аккаунта, с которого ему писали, и записать ответ."""
    text = text or ""
    if not text.strip():
        raise AnswerError("Пустой ответ")
    reply = await store.get_reply(reply_id)
    if not reply:
        raise AnswerError("Ответ не найден")
    if not reply.valid:
        raise AnswerError("Это сообщение со ссылкой (редирект) — отвечать не на что")
    acc = await store.get_account(reply.account_id) if reply.account_id else None
    if not acc or not acc.telethon_session:
        raise AnswerError("Аккаунт без session — ответить нельзя")

    proxy = await store.peek_proxy(acc.id)
    try:
        await asyncio.wait_for(account_lock(acc.id).acquire(), LOCK_WAIT_SEC)
    except asyncio.TimeoutError as e:
        raise AnswerError("Аккаунт занят отправкой, попробуйте ещё раз") from e
    try:
        async with telethon_client(acc.telethon_session, proxy) as client:
            try:
                entity = await client.get_input_entity(reply.peer_id)
            except Exception:
                contact = await store.get_contact_row(reply.contact_id) if reply.contact_id else None
                if not contact:
                    raise AnswerError("Не удалось найти собеседника в аккаунте")
                entity = await resolve_peer(client, contact)
            async with client.action(entity, "typing"):
                await asyncio.sleep(min(4.0, max(0.6, len(text) / 25)))
            sent = await client.send_message(
                entity,
                text,
                formatting_entities=to_telethon_entities(entities or []) or None,
                link_preview=False,
            )
            try:
                await client.send_read_acknowledge(entity)
            except Exception:
                pass
    except AnswerError:
        raise
    except Exception as e:
        raise AnswerError(str(e)[:300] or e.__class__.__name__) from e
    finally:
        account_lock(acc.id).release()

    return await store.add_answer(reply, text, tg_msg_id=int(sent.id), source=source)
