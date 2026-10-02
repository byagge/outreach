"""Ежедневный дайджест: сводка за 24 часа + XLSX в чат в заданный час (daily_report_hour)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.types import BufferedInputFile

from app.bot.notify import notify_chats
from app.config import get_settings
from app.store import Store
from app.ui.stats_screens import overview_html
from app.utils.report import build_report_xlsx

log = logging.getLogger("outreach.digest")


async def send_digest(store: Store, bot: Bot, days: int = 1) -> int:
    data, report = await build_report_xlsx(store, days=days)
    text = overview_html(report, "24 ч" if days == 1 else f"{days} дн")
    sent = 0
    for chat_id in await notify_chats(store):
        try:
            await bot.send_message(chat_id, text, parse_mode="HTML")
            await bot.send_document(
                chat_id,
                BufferedInputFile(data, filename=f"outreach_report_{datetime.now():%Y-%m-%d}.xlsx"),
            )
            sent += 1
        except Exception as e:
            log.warning("digest to %s failed: %s", chat_id, e)
    return sent


async def run_daily_digest(store: Store, bot: Bot) -> None:
    tz = get_settings().tz
    while True:
        await asyncio.sleep(30)
        try:
            raw = await store.get_setting("daily_report_hour", "-1")
            hour = int(raw) if raw.lstrip("-").isdigit() else -1
            if hour < 0:
                continue
            now = datetime.now(tz)
            today = now.date().isoformat()
            if now.hour != hour or await store.get_setting("daily_report_last", "") == today:
                continue
            await store.set_setting("daily_report_last", today)
            await send_digest(store, bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("daily digest failed")
