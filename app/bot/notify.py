from __future__ import annotations

import logging

from aiogram import Bot

from app.bot.keyboards import reply_notify_kb
from app.config import get_settings
from app.models import Reply
from app.store import Store
from app.ui.stats_screens import reply_notification_html

log = logging.getLogger("outreach.notify")


async def notify_chats(store: Store) -> list[int]:
    """Админы из .env + последний чат, где пользовались ботом."""
    chats = set(get_settings().admins)
    raw = await store.get_setting("notify_chat_id", "")
    if raw.lstrip("-").isdigit():
        chats.add(int(raw))
    return sorted(chats)


async def remember_chat(store: Store, chat_id: int) -> None:
    await store.set_setting("notify_chat_id", str(chat_id))


async def send_reply_notification(bot: Bot, store: Store, reply: Reply) -> int:
    """Уведомить в чат: кто ответил, что написал, кнопка «Ответить». Возвращает число чатов."""
    sent = 0
    for chat_id in await notify_chats(store):
        try:
            await bot.send_message(
                chat_id,
                reply_notification_html(reply),
                parse_mode="HTML",
                reply_markup=reply_notify_kb(reply.id),
            )
            sent += 1
        except Exception as e:
            log.warning("notify %s failed: %s", chat_id, e)
    if not sent:
        raise RuntimeError("Некому слать уведомление: нет ADMIN_IDS и ни одного /start")
    return sent
