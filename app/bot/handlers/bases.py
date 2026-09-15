from __future__ import annotations

from html import escape
from io import BytesIO

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.ai.contacts import parse_contacts_file, parse_lines, parse_xlsx_all_sheets
from app.bot.keyboards import MenuCB, bases_kb, base_kb, cancel_kb, confirm_kb
from app.bot.render import ask_input, finish_input, safe_edit
from app.bot.states import AddBase
from app.context import ctx
from app.ui.screens import base_html, bases_html, prompt_html
from app.utils.export import contacts_to_csv, contacts_to_txt, contacts_to_xlsx

router = Router()


async def _bases_screen(page: int = 0):
    bases = await ctx.store.list_bases()
    stats = {}
    for b in bases:
        stats[b.id] = await ctx.store.base_stats(b.id)
    return bases_html(bases, stats), bases_kb(bases, page)


async def _base_screen(base_id: int, page: int = 0):
    base = await ctx.store.get_base(base_id)
    if not base:
        return None, None
    stats = await ctx.store.base_stats(base_id)
    preview = await ctx.store.list_contacts_for_base(base_id, page=page)
    return base_html(base, stats, preview), base_kb(base, stats["total"], page)


@router.callback_query(MenuCB.filter(F.a == "bases"))
async def cb_bases(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _bases_screen(callback_data.p)
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "base"))
async def cb_base(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    payload = await _base_screen(callback_data.i, callback_data.p)
    if not payload[0]:
        await query.answer("База не найдена", show_alert=True)
        return
    await safe_edit(query, payload[0], payload[1])


@router.callback_query(MenuCB.filter(F.a == "base_on"))
async def cb_base_on(query: CallbackQuery, callback_data: MenuCB) -> None:
    base = await ctx.store.toggle_base(callback_data.i)
    if not base:
        await query.answer("Нет базы", show_alert=True)
        return
    await query.answer("Включена" if base.enabled else "Выключена")
    payload = await _base_screen(base.id)
    if payload[0]:
        await safe_edit(query, payload[0], payload[1])


@router.callback_query(MenuCB.filter(F.a == "base_add"))
async def cb_base_add(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddBase.name)
    text = prompt_html("Новая база", "Имя листа / базы:", "users")
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(AddBase.name, F.text)
async def on_base_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Пустое имя")
        return
    base = await ctx.store.add_base(name)
    await state.update_data(base_id=base.id)
    await state.set_state(AddBase.file)
    text = prompt_html(
        "Загрузка",
        f"База <b>{escape(name)}</b> создана.\n"
        "Пришлите файл или текст (txt, csv, xlsx, md, sql, json).\n"
        "Xlsx — каждый лист можно загрузить отдельной базой.",
        "inbox",
    )
    await ask_input(message, text)


@router.callback_query(MenuCB.filter(F.a == "base_imp"))
async def cb_base_imp(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.update_data(base_id=callback_data.i)
    await state.set_state(AddBase.file)
    text = prompt_html(
        "Загрузить",
        "Пришлите файл или список контактов.\n"
        "Форматы: txt, csv, xlsx, md, sql, json.",
        "inbox",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


async def _ingest_base(message: Message, base_id: int, parsed, multi: dict | None = None) -> None:
    if multi:
        added_total = 0
        skipped_total = 0
        sheets = list(multi.items())
        first_name, first_result = sheets[0]
        await ctx.store.rename_base(base_id, first_name[:60])
        usable = [c for c in first_result.contacts if c.kind != "unknown"]
        added, skipped = await ctx.store.add_contacts(usable, base_id)
        added_total += added
        skipped_total += skipped
        for sheet_name, sheet_result in sheets[1:]:
            base = await ctx.store.add_base(sheet_name[:60])
            usable = [c for c in sheet_result.contacts if c.kind != "unknown"]
            added, skipped = await ctx.store.add_contacts(usable, base.id)
            added_total += added
            skipped_total += skipped
        body = (
            f"Листов: <b>{len(multi)}</b> · первый → база #{base_id}\n"
            f"Добавлено: <b>{added_total}</b> · дубли: {skipped_total}"
        )
    else:
        usable = [c for c in parsed.contacts if c.kind != "unknown"]
        added, skipped = await ctx.store.add_contacts(usable, base_id)
        notes = ", ".join(parsed.notes) if parsed.notes else "lines"
        body = (
            f"Разобрал как <code>{escape(notes)}</code>\n"
            f"Добавлено: <b>{added}</b> · дубли: {skipped}"
        )
    payload = await _base_screen(base_id)
    if payload[0]:
        await finish_input(message, prompt_html("База", body, "users") + "\n\n" + payload[0], payload[1])
    else:
        text, markup = await _bases_screen(0)
        await finish_input(message, prompt_html("База", body, "users") + "\n\n" + text, markup)


@router.message(AddBase.file, F.document)
async def on_base_file(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    base_id = int(data.get("base_id") or await ctx.store.default_base_id())
    doc = message.document
    buf = BytesIO()
    await message.bot.download(doc, destination=buf)
    raw = buf.getvalue()
    await state.clear()
    name = (doc.file_name or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        multi = parse_xlsx_all_sheets(raw)
        if len(multi) > 1:
            await _ingest_base(message, base_id, None, multi=multi)
            return
    parsed = parse_contacts_file(raw, doc.file_name or "file.txt")
    await _ingest_base(message, base_id, parsed)


@router.message(AddBase.file, F.text)
async def on_base_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    base_id = int(data.get("base_id") or await ctx.store.default_base_id())
    await state.clear()
    parsed = parse_lines(message.text or "")
    parsed.notes.append("paste")
    await _ingest_base(message, base_id, parsed)


@router.callback_query(MenuCB.filter(F.a == "base_exp"))
async def cb_base_exp(query: CallbackQuery, callback_data: MenuCB) -> None:
    base = await ctx.store.get_base(callback_data.i)
    if not base:
        await query.answer("Нет базы", show_alert=True)
        return
    contacts = await ctx.store.export_contacts(base.id)
    if not contacts:
        await query.answer("База пустая", show_alert=True)
        return
    safe = base.name.replace(" ", "_")[:30]
    for ext, data, mime in (
        ("txt", contacts_to_txt(contacts), "text/plain"),
        ("csv", contacts_to_csv(contacts), "text/csv"),
        ("xlsx", contacts_to_xlsx(contacts), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ):
        await query.message.answer_document(
            BufferedInputFile(data, filename=f"{safe}.{ext}"),
        )
    await query.answer(f"Экспорт {len(contacts)} контактов")


@router.callback_query(MenuCB.filter(F.a == "base_del"))
async def cb_base_del(query: CallbackQuery, callback_data: MenuCB) -> None:
    await safe_edit(
        query,
        prompt_html("Удалить базу", "Удалить базу и все её контакты?", "warn"),
        confirm_kb(MenuCB(a="base_del2", i=callback_data.i), MenuCB(a="base", i=callback_data.i)),
    )


@router.callback_query(MenuCB.filter(F.a == "base_del2"))
async def cb_base_del2(query: CallbackQuery, callback_data: MenuCB) -> None:
    await ctx.store.delete_base(callback_data.i)
    text, markup = await _bases_screen(0)
    await safe_edit(query, text, markup)
