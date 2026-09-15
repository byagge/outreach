from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards import MenuCB, history_kb
from app.bot.render import safe_edit
from app.context import ctx
from app.ui.screens import history_html

router = Router()


@router.callback_query(MenuCB.filter(F.a == "history"))
async def cb_history(query: CallbackQuery) -> None:
    jobs = await ctx.store.recent_jobs(12)
    sends = await ctx.store.recent_sends(16)
    await safe_edit(query, history_html(jobs, sends), history_kb())
