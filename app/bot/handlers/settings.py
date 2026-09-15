from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import MenuCB, cancel_kb, settings_kb
from app.bot.render import ask_input, finish_input, safe_edit
from app.bot.states import EditSettings
from app.context import ctx
from app.ui.screens import prompt_html, settings_html

router = Router()


@router.callback_query(MenuCB.filter(F.a == "settings"))
async def cb_settings(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    settings = await ctx.store.outreach_settings()
    await safe_edit(query, settings_html(settings), settings_kb())


@router.callback_query(MenuCB.filter(F.a == "s_delay"))
async def cb_delay(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditSettings.delay)
    text = prompt_html(
        "Интервал",
        "Пауза между сообщениями <b>внутри одного аккаунта</b>, секунды.\n"
        "Формат: <code>40-90</code> или <code>60</code>.",
        "clock",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(EditSettings.delay, F.text)
async def on_delay(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").replace("—", "-").replace("–", "-").strip()
    parts = [p.strip() for p in raw.replace(",", "-").split("-") if p.strip()]
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        await message.answer("Нужны числа, например 40-90")
        return
    if not nums:
        await message.answer("Пусто")
        return
    lo = max(1, nums[0])
    hi = max(lo, nums[-1])
    await state.clear()
    settings = await ctx.store.update_settings(delay_min=lo, delay_max=hi)
    await finish_input(message, settings_html(settings), settings_kb())


@router.callback_query(MenuCB.filter(F.a == "s_type"))
async def cb_type(query: CallbackQuery) -> None:
    settings = await ctx.store.outreach_settings()
    settings = await ctx.store.update_settings(typing=not settings.typing)
    await query.answer("Печатает: " + ("да" if settings.typing else "нет"))
    await safe_edit(query, settings_html(settings), settings_kb())


@router.callback_query(MenuCB.filter(F.a == "s_var"))
async def cb_var(query: CallbackQuery) -> None:
    settings = await ctx.store.outreach_settings()
    nxt = "random" if settings.variant_mode == "rotate" else "rotate"
    settings = await ctx.store.update_settings(variant_mode=nxt)
    await query.answer(settings.variant_mode)
    await safe_edit(query, settings_html(settings), settings_kb())


@router.callback_query(MenuCB.filter(F.a == "s_prot"))
async def cb_prot(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditSettings.proxy_every)
    text = prompt_html(
        "Ротация прокси",
        "Через сколько сообщений аккаунт меняет прокси из своего пула.\n"
        "Число, например <code>1</code> — каждый раз.",
        "shield",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.callback_query(MenuCB.filter(F.a == "s_between"))
async def cb_between(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditSettings.between_delay)
    text = prompt_html(
        "Между аккаунтами",
        "Пауза между отправками с <b>разных</b> аккаунтов, сек.\n"
        "По умолчанию <code>0</code> — без паузы.\n"
        "Формат: <code>0</code> или <code>5-15</code>.",
        "clock",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(EditSettings.between_delay, F.text)
async def on_between(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").replace("—", "-").strip()
    parts = [p.strip() for p in raw.replace(",", "-").split("-") if p.strip()]
    if not parts or parts[0] == "0":
        lo, hi = 0, 0
    else:
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            await message.answer("Нужны числа")
            return
        lo = max(0, nums[0])
        hi = max(lo, nums[-1])
    await state.clear()
    settings = await ctx.store.update_settings(between_delay_min=lo, between_delay_max=hi)
    await finish_input(message, settings_html(settings), settings_kb())


@router.callback_query(MenuCB.filter(F.a == "s_cont"))
async def cb_cont(query: CallbackQuery) -> None:
    settings = await ctx.store.outreach_settings()
    settings = await ctx.store.update_settings(continuous=not settings.continuous)
    await query.answer("24/7: " + ("да" if settings.continuous else "нет"))
    await safe_edit(query, settings_html(settings), settings_kb())


@router.message(EditSettings.proxy_every, F.text)
async def on_prot(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        await message.answer("Нужно целое ≥ 1")
        return
    await state.clear()
    settings = await ctx.store.update_settings(rotate_proxy_every=int(raw))
    await finish_input(message, settings_html(settings), settings_kb())
