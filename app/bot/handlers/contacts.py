from __future__ import annotations

from html import escape
from io import BytesIO

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.ai.contacts import parse_contacts_file, parse_lines
from app.bot.keyboards import MenuCB, cancel_kb, confirm_kb, contacts_kb
from app.bot.render import ask_input, finish_input, safe_edit
from app.bot.states import AddContacts
from app.context import ctx
from app.ui.screens import contacts_html, prompt_html

router = Router()


async def _screen(page: int = 0):
    counts = await ctx.store.counts()
    kinds = await ctx.store.contact_kind_counts()
    preview = await ctx.store.list_contacts(page=page, per_page=8)
    return contacts_html(counts, kinds, preview), contacts_kb(counts.contacts, page)


@router.callback_query(MenuCB.filter(F.a == "contacts"))
async def cb_contacts(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    from app.bot.handlers.bases import cb_bases

    await cb_bases(query, callback_data, state)


@router.callback_query(MenuCB.filter(F.a == "ct_add"))
async def cb_ct_add(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddContacts.file)
    text = prompt_html(
        "База",
        "Пришлите файл или текст. Каждая новая строка — контакт.\n"
        "Понимаю <b>txt, csv, xlsx, md, json</b> и просто список.\n"
        f"{escape('Примеры: @user · t.me/user · +79991234567 · 123456789')}\n"
        "ИИ разметит тип сам. Дубликаты пропускаются. Можно докидывать к уже загруженной базе.",
        "users",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


async def _ingest(message: Message, parsed) -> None:
    usable = [c for c in parsed.contacts if c.kind != "unknown"]
    unknown = [c for c in parsed.contacts if c.kind == "unknown"]
    added, skipped = await ctx.store.add_contacts(usable)
    kinds: dict[str, int] = {}
    for c in usable:
        kinds[c.kind] = kinds.get(c.kind, 0) + 1
    kind_s = ", ".join(f"{k} {v}" for k, v in kinds.items()) or "—"
    notes = ", ".join(parsed.notes) if parsed.notes else "lines"
    body = (
        f"Разобрал как <code>{escape(notes)}</code>\n"
        f"Добавлено: <b>{added}</b> · дубли: {skipped} · "
        f"мусор: {parsed.skipped + len(unknown)}\n"
        f"{escape(kind_s)}"
    )
    text, markup = await _screen(0)
    await finish_input(message, prompt_html("База", body, "users") + "\n\n" + text, markup)


@router.message(AddContacts.file, F.document)
async def on_ct_file(message: Message, state: FSMContext) -> None:
    doc = message.document
    buf = BytesIO()
    await message.bot.download(doc, destination=buf)
    data = buf.getvalue()
    await state.clear()
    parsed = parse_contacts_file(data, doc.file_name or "file.txt")
    await _ingest(message, parsed)


@router.message(AddContacts.file, F.text)
async def on_ct_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    parsed = parse_lines(message.text or "")
    parsed.notes.append("paste")
    await _ingest(message, parsed)


@router.callback_query(MenuCB.filter(F.a == "ct_retry"))
async def cb_retry(query: CallbackQuery) -> None:
    n = await ctx.store.reset_errors_to_pending()
    await query.answer(f"Вернул {n}")
    text, markup = await _screen(0)
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "ct_clear"))
async def cb_clear(query: CallbackQuery) -> None:
    await safe_edit(
        query,
        prompt_html(
            "Очистить базу",
            "Удалить все контакты? История отправок останется.",
            "warn",
        ),
        confirm_kb(MenuCB(a="ct_clear2"), MenuCB(a="contacts"), yes_text="Удалить"),
    )


@router.callback_query(MenuCB.filter(F.a == "ct_clear2"))
async def cb_clear2(query: CallbackQuery) -> None:
    await ctx.store.clear_contacts()
    text, markup = await _screen(0)
    await safe_edit(query, text, markup)
