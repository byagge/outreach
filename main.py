from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot import setup_routers
from app.bot.middlewares import AdminOnlyMiddleware
from app.config import ensure_dirs, get_settings
from app.bot.notify import send_reply_notification
from app.context import ctx
from app.jobs.digest import run_daily_digest
from app.jobs.replies import run_reply_listener
from app.store import Store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("outreach")


async def main() -> None:
    ensure_dirs()
    settings = get_settings()
    if not settings.bot_token:
        raise SystemExit("Задайте BOT_TOKEN в .env (см. .env.example)")
    if not settings.admins:
        log.warning("ADMIN_IDS пуст — бот отвечает всем. Заполните .env")

    store = Store()
    await store.init()
    ctx.store = store

    bot = Bot(token=settings.bot_token)
    ctx.bot = bot
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(AdminOnlyMiddleware())
    setup_routers(dp)

    async def notify(reply) -> None:
        await send_reply_notification(bot, store, reply)

    background = [
        asyncio.create_task(run_reply_listener(store, notify), name="reply-listener"),
        asyncio.create_task(run_daily_digest(store, bot), name="daily-digest"),
    ]
    log.info("Outreach bot starting")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
