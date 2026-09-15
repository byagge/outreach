from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards import MenuCB, run_kb
from app.bot.render import safe_edit
from app.context import ctx
from app.jobs.outreach import run_outreach
from app.jobs.runtime import runtime
from app.ui.screens import run_html

router = Router()


async def _screen():
    counts = await ctx.store.counts()
    accounts = await ctx.store.list_accounts()
    settings = await ctx.store.outreach_settings()
    running = runtime.is_running("outreach", 0)
    return run_html(counts, accounts, settings), run_kb(accounts, running)


@router.callback_query(MenuCB.filter(F.a == "run"))
async def cb_run(query: CallbackQuery) -> None:
    text, markup = await _screen()
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "run_asg"))
async def cb_run_asg(query: CallbackQuery, callback_data: MenuCB) -> None:
    acc = await ctx.store.toggle_assigned(callback_data.i)
    if not acc:
        await query.answer("Нет аккаунта", show_alert=True)
        return
    await query.answer("Назначен" if acc.assigned else "Снят")
    text, markup = await _screen()
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "run_go"))
async def cb_run_go(query: CallbackQuery) -> None:
    counts = await ctx.store.counts()
    settings = await ctx.store.outreach_settings()
    accounts = [a for a in await ctx.store.list_accounts() if a.assigned and a.has_telethon]
    if not accounts:
        await query.answer("Нет назначенных аккаунтов с session", show_alert=True)
        return
    if counts.pending <= 0 and not settings.continuous:
        await query.answer("База пустая — загрузите контакты", show_alert=True)
        return
    if counts.texts <= 0:
        await query.answer("Нет текстов", show_alert=True)
        return
    if runtime.is_running("outreach", 0):
        await query.answer("Уже запущено", show_alert=True)
        return
    await query.answer("Запускаю" if counts.pending > 0 else "24/7 — жду базу")
    chat_id = query.from_user.id if query.from_user else None
    try:
        runtime.spawn("outreach", 0, run_outreach(ctx.store, query.bot, chat_id))
    except RuntimeError as e:
        await query.answer(str(e), show_alert=True)
        return
    text, markup = await _screen()
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "run_stop"))
async def cb_run_stop(query: CallbackQuery) -> None:
    if not runtime.is_running("outreach", 0):
        await query.answer("Уже не запущено")
    else:
        runtime.request_cancel("outreach", 0)
        await query.answer("Останавливаю…")
    text, markup = await _screen()
    await safe_edit(query, text, markup)
