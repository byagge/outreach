from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import BTN_CANCEL, BTN_PANEL, MenuCB, main_menu, panel_keyboard
from app.bot.render import safe_edit
from app.context import ctx
from app.jobs.runtime import runtime
from app.ui.emoji import pe
from app.ui.screens import home_html, info_html, prompt_html

router = Router()


async def show_home(event: Message | CallbackQuery) -> None:
    text = await home_html(ctx.store)
    markup = main_menu(runtime.is_running("outreach", 0))
    if isinstance(event, Message):
        await event.answer(text, reply_markup=markup, parse_mode="HTML")
        return
    await safe_edit(event, text, markup)


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        f"{pe('cube')} <b>Outreach</b>",
        reply_markup=panel_keyboard(),
        parse_mode="HTML",
    )
    await message.answer(
        await home_html(ctx.store),
        reply_markup=main_menu(runtime.is_running("outreach", 0)),
        parse_mode="HTML",
    )


@router.message(F.text == BTN_PANEL)
async def cmd_panel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        await home_html(ctx.store),
        reply_markup=main_menu(runtime.is_running("outreach", 0)),
        parse_mode="HTML",
    )


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
@router.message(F.text.casefold() == "отмена")
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer(
            prompt_html("Отмена", "Нет активного ввода — нечего отменять."),
            reply_markup=panel_keyboard(),
            parse_mode="HTML",
        )
        return
    await state.clear()
    await message.answer(
        prompt_html("Отмена", "Операция отменена. Данные не сохранены."),
        reply_markup=panel_keyboard(),
        parse_mode="HTML",
    )
    await show_home(message)


@router.callback_query(MenuCB.filter(F.a == "home"))
async def cb_home(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show_home(query)


@router.callback_query(MenuCB.filter(F.a == "cancel"))
async def cb_cancel(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show_home(query)


@router.callback_query(MenuCB.filter(F.a == "info"))
async def cb_info(query: CallbackQuery) -> None:
    await safe_edit(
        query,
        info_html(),
        main_menu(runtime.is_running("outreach", 0)),
    )
