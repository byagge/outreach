from __future__ import annotations

import math
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import (
    MenuCB,
    cancel_kb,
    reply_detail_kb,
    replies_kb,
    panel_keyboard,
)
from app.bot.render import ask_input, safe_edit
from app.bot.states import ReplyAnswerState
from app.context import ctx
from app.jobs.replies import AnswerError, send_answer
from app.ui.emoji import pe
from app.ui.stats_screens import reply_detail_html, replies_list_html
from app.utils.entities import from_aiogram_message

router = Router()
PER_PAGE = 8


@router.callback_query(MenuCB.filter(F.a == "rp"))
async def cb_replies(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    total = await ctx.store.count_replies(status="new", valid=True)
    pages = max(1, math.ceil(total / PER_PAGE))
    page = max(0, min(callback_data.p, pages - 1))
    items = await ctx.store.list_replies(
        status="new", valid=True, limit=PER_PAGE, offset=page * PER_PAGE
    )
    await safe_edit(query, replies_list_html(items, total, page, pages), replies_kb(items, page, pages))


@router.callback_query(MenuCB.filter(F.a == "rp_v"))
async def cb_reply_view(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    reply = await ctx.store.get_reply(callback_data.i)
    if not reply:
        await query.answer("Ответ не найден", show_alert=True)
        return
    thread = await ctx.store.reply_thread(reply)
    await safe_edit(
        query, reply_detail_html(reply, thread), reply_detail_kb(reply.id, reply.status == "answered")
    )


@router.callback_query(MenuCB.filter(F.a == "rp_ign"))
async def cb_reply_ignore(query: CallbackQuery, callback_data: MenuCB) -> None:
    reply = await ctx.store.set_reply_status(callback_data.i, "ignored")
    if not reply:
        await query.answer("Ответ не найден", show_alert=True)
        return
    await query.answer("Пропущено")
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@router.callback_query(MenuCB.filter(F.a == "rp_ans"))
async def cb_reply_answer(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    reply = await ctx.store.get_reply(callback_data.i)
    if not reply or not reply.valid:
        await query.answer("Ответ не найден", show_alert=True)
        return
    await state.set_state(ReplyAnswerState.text)
    await state.update_data(reply_id=reply.id)
    await ask_input(
        query,
        f"{pe('mega')} <b>Ответ для {escape(reply.who)}</b>\n"
        "Пришлите текст одним сообщением — уйдёт с того же аккаунта.\n"
        "Отмена — кнопка внизу.",
    )


@router.message(ReplyAnswerState.text, F.text)
async def on_reply_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    reply_id = int(data.get("reply_id") or 0)
    await state.clear()
    text, entities = from_aiogram_message(message)
    wait = await message.answer("Отправляю…", reply_markup=panel_keyboard())
    try:
        await send_answer(ctx.store, reply_id, text, entities, source="bot")
    except AnswerError as e:
        await wait.edit_text(
            f"{pe('warn')} Не отправлено: {escape(str(e))}", parse_mode="HTML"
        )
        await message.answer(
            "Попробовать ещё раз?", reply_markup=reply_detail_kb(reply_id, False)
        )
        return
    reply = await ctx.store.get_reply(reply_id)
    who = escape(reply.who) if reply else "собеседнику"
    await wait.edit_text(f"{pe('check')} Отправлено → <b>{who}</b>", parse_mode="HTML")
    await message.answer(
        f"{pe('inbox')} Ждут ответа: {await ctx.store.unanswered_replies_count()}",
        reply_markup=reply_detail_kb(reply_id, True),
        parse_mode="HTML",
    )
