from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import MenuCB, cancel_kb, confirm_kb, text_kb, texts_kb
from app.bot.render import ask_input, finish_input, safe_edit
from app.bot.states import AddText
from app.config import TEXTS_DIR
from app.context import ctx
from app.ui.screens import prompt_html, text_html, texts_html
from app.utils.entities import from_aiogram_message

router = Router()


@router.callback_query(MenuCB.filter(F.a == "texts"))
async def cb_texts(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    items = await ctx.store.list_texts()
    await safe_edit(query, texts_html(items), texts_kb(items, callback_data.p))


@router.callback_query(MenuCB.filter(F.a == "tx"))
async def cb_tx(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    item = await ctx.store.get_text(callback_data.i)
    if not item:
        await query.answer("Нет текста", show_alert=True)
        return
    await safe_edit(query, text_html(item), text_kb(item))


@router.callback_query(MenuCB.filter(F.a == "tx_add"))
async def cb_tx_add(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddText.message)
    text = prompt_html(
        "Вариант текста",
        "Пришлите одним сообщением. Сохранятся текст, premium emoji, "
        "жирный/ссылки и фото.\n"
        "Можно несколько вариантов — на рассылке пойдут по очереди (или рандом).",
        "mega",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(AddText.message, F.text | F.photo | F.caption | F.document)
async def on_text(message: Message, state: FSMContext) -> None:
    if message.document and not (message.document.mime_type or "").startswith("image/"):
        if not (message.text or message.caption):
            await message.answer("Нужен текст или фото")
            return
    text, entities = from_aiogram_message(message)
    if not text.strip() and not message.photo and not (
        message.document and (message.document.mime_type or "").startswith("image/")
    ):
        await message.answer("Пустое сообщение")
        return
    n = len(await ctx.store.list_texts()) + 1
    photo_path = ""
    if message.photo:
        dest = TEXTS_DIR / f"v{n}.jpg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        await message.bot.download(message.photo[-1], destination=dest)
        photo_path = str(dest)
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        dest = TEXTS_DIR / f"v{n}_{message.document.file_name or 'file'}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        await message.bot.download(message.document, destination=dest)
        photo_path = str(dest)
    await state.clear()
    item = await ctx.store.add_text(text, entities, photo_path, title=f"вариант #{n}")
    items = await ctx.store.list_texts()
    await finish_input(
        message,
        prompt_html("Тексты", f"Сохранён <b>{item.title}</b>. Всего вариантов: {len(items)}", "mega")
        + "\n\n"
        + texts_html(items),
        texts_kb(items),
    )


@router.callback_query(MenuCB.filter(F.a == "tx_on"))
async def cb_tx_on(query: CallbackQuery, callback_data: MenuCB) -> None:
    item = await ctx.store.get_text(callback_data.i)
    if not item:
        await query.answer("Нет текста", show_alert=True)
        return
    item = await ctx.store.update_text(item.id, enabled=0 if item.enabled else 1)
    if not item:
        await query.answer("Удалён", show_alert=True)
        return
    await query.answer("Ок")
    await safe_edit(query, text_html(item), text_kb(item))


@router.callback_query(MenuCB.filter(F.a == "tx_del"))
async def cb_tx_del(query: CallbackQuery, callback_data: MenuCB) -> None:
    await safe_edit(
        query,
        prompt_html("Удалить текст", "Убрать этот вариант?", "warn"),
        confirm_kb(
            MenuCB(a="tx_del2", i=callback_data.i),
            MenuCB(a="tx", i=callback_data.i),
            yes_text="Удалить",
        ),
    )


@router.callback_query(MenuCB.filter(F.a == "tx_del2"))
async def cb_tx_del2(query: CallbackQuery, callback_data: MenuCB) -> None:
    await ctx.store.delete_text(callback_data.i)
    items = await ctx.store.list_texts()
    await safe_edit(query, texts_html(items), texts_kb(items))
