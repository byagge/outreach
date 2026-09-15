from __future__ import annotations

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import input_cancel_keyboard, panel_keyboard


def _msg(event: Message | CallbackQuery) -> Message | None:
    if isinstance(event, CallbackQuery):
        return event.message
    return event


def _has_media(message: Message | None) -> bool:
    if message is None:
        return False
    return bool(message.photo or message.document or message.video or message.animation)


async def _ack(event: Message | CallbackQuery) -> None:
    if isinstance(event, CallbackQuery):
        try:
            await event.answer()
        except Exception:
            pass


async def safe_edit(
    event: Message | CallbackQuery,
    text: str,
    reply_markup=None,
    *,
    html: bool = True,
) -> None:
    kwargs: dict = {"reply_markup": reply_markup}
    if html:
        kwargs["parse_mode"] = ParseMode.HTML
    message = _msg(event)
    media = _has_media(message)

    if isinstance(event, CallbackQuery) and message is not None:
        try:
            if media:
                try:
                    await message.delete()
                except Exception:
                    pass
                await message.answer(text, **kwargs)
            else:
                await message.edit_text(text, **kwargs)
        except TelegramBadRequest as e:
            if "not modified" not in str(e).lower():
                await message.answer(text, **kwargs)
        except Exception:
            await message.answer(text, **kwargs)
        await _ack(event)
        return

    if "reply_markup" not in kwargs or kwargs["reply_markup"] is None:
        kwargs["reply_markup"] = panel_keyboard()
    await event.answer(text, **kwargs)


async def ask_input(event: Message | CallbackQuery, text: str) -> None:
    if isinstance(event, CallbackQuery):
        await _ack(event)
        await event.message.answer(
            text,
            reply_markup=input_cancel_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return
    await event.answer(text, reply_markup=input_cancel_keyboard(), parse_mode=ParseMode.HTML)


async def finish_input(message: Message, text: str, markup) -> None:
    await message.answer("Готово", reply_markup=panel_keyboard())
    await message.answer(text, reply_markup=markup, parse_mode=ParseMode.HTML)
