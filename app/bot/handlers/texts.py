from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import MenuCB, cancel_kb, confirm_kb, text_kb, texts_kb
from app.bot.render import ask_input, finish_input, safe_edit
from app.bot.states import AddText, EditText
from app.config import TEXTS_DIR
from app.context import ctx
from app.ui.screens import prompt_html, text_html, texts_html
from app.utils.entities import from_aiogram_message

router = Router()


async def _save_photo(message: Message, prefix: str) -> str:
    if message.photo:
        dest = TEXTS_DIR / f"{prefix}.jpg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        await message.bot.download(message.photo[-1], destination=dest)
        return str(dest)
    if message.document and (message.document.mime_type or "").startswith("image/"):
        dest = TEXTS_DIR / f"{prefix}_{message.document.file_name or 'file'}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        await message.bot.download(message.document, destination=dest)
        return str(dest)
    return ""


@router.callback_query(MenuCB.filter(F.a == "texts"))
async def cb_texts(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    items = await ctx.store.list_texts()
    page = max(0, callback_data.p)
    await safe_edit(query, texts_html(items, page=page), texts_kb(items, page))


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
    photo_path = await _save_photo(message, f"v{n}")
    await state.clear()
    item = await ctx.store.add_text(text, entities, photo_path, title=f"вариант #{n}")
    items = await ctx.store.list_texts()
    page = max(0, (len(items) - 1) // 8)
    await finish_input(
        message,
        prompt_html("Тексты", f"Сохранён <b>{item.title}</b>. Всего вариантов: {len(items)}", "mega")
        + "\n\n"
        + texts_html(items, page=page),
        texts_kb(items, page),
    )


@router.callback_query(MenuCB.filter(F.a == "tx_edit"))
async def cb_tx_edit(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    item = await ctx.store.get_text(callback_data.i)
    if not item:
        await query.answer("Нет текста", show_alert=True)
        return
    await state.set_state(EditText.message)
    await state.update_data(text_id=item.id)
    text = prompt_html(
        "Изменить оффер",
        f"Сейчас: <b>{item.title or f'#{item.id}'}</b>\n\n"
        "Пришлите новое сообщение — текст, premium emoji, оформление и фото "
        "(если фото есть в новом сообщении — заменит старое).",
        "hammer",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(EditText.message, F.text | F.photo | F.caption | F.document)
async def on_tx_edit(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text_id = int(data.get("text_id") or 0)
    await state.clear()
    item = await ctx.store.get_text(text_id)
    if not item:
        await message.answer("Оффер не найден")
        return
    text, entities = from_aiogram_message(message)
    photo_path = await _save_photo(message, f"v{text_id}_edit")
    fields: dict = {
        "text": text,
        "entities_json": json.dumps(entities, ensure_ascii=False),
    }
    if photo_path:
        fields["photo_path"] = photo_path
    if not (text or "").strip() and not photo_path and not item.photo_path:
        await message.answer("Пустое сообщение")
        return
    if not (text or "").strip() and not photo_path:
        # только фото не прислали — оставляем старый текст пустым нельзя если нет фото
        if not item.photo_path:
            await message.answer("Нужен текст или фото")
            return
    updated = await ctx.store.update_text(text_id, **fields)
    await finish_input(
        message,
        prompt_html("Оффер обновлён", f"<b>{updated.title if updated else ''}</b>", "check")
        + "\n\n"
        + text_html(updated or item),
        text_kb(updated or item),
    )


@router.callback_query(MenuCB.filter(F.a == "tx_ren"))
async def cb_tx_ren(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    item = await ctx.store.get_text(callback_data.i)
    if not item:
        await query.answer("Нет текста", show_alert=True)
        return
    await state.set_state(EditText.title)
    await state.update_data(text_id=item.id)
    text = prompt_html(
        "Название оффера",
        f"Сейчас: <b>{item.title or f'#{item.id}'}</b>\nПришлите новое название.",
        "bookmark",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(EditText.title, F.text)
async def on_tx_ren(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    text_id = int(data.get("text_id") or 0)
    title = (message.text or "").strip()[:80]
    if not title:
        await message.answer("Пустое название")
        return
    item = await ctx.store.update_text(text_id, title=title)
    if not item:
        await message.answer("Не найден")
        return
    await finish_input(
        message,
        prompt_html("Название", f"Сохранено: <b>{title}</b>", "check") + "\n\n" + text_html(item),
        text_kb(item),
    )


@router.callback_query(MenuCB.filter(F.a == "tx_nophoto"))
async def cb_tx_nophoto(query: CallbackQuery, callback_data: MenuCB) -> None:
    item = await ctx.store.update_text(callback_data.i, photo_path="")
    if not item:
        await query.answer("Нет текста", show_alert=True)
        return
    if not (item.text or "").strip():
        await query.answer("Нельзя убрать фото: нет текста", show_alert=True)
        return
    await query.answer("Фото убрано")
    await safe_edit(query, text_html(item), text_kb(item))


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
    await safe_edit(query, texts_html(items, page=0), texts_kb(items, 0))
