from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import (
    MenuCB,
    bases_kb,
    banwords_kb,
    cancel_kb,
    collect_accounts_kb,
    collect_kb,
)
from app.bot.render import ask_input, finish_input, safe_edit
from app.bot.states import Banwords as BanwordsState
from app.bot.states import CollectChat
from app.context import ctx
from app.tg.client import telethon_client
from app.tg.collect import CollectResult, collect_dm_history, collect_from_chat
from app.ui.screens import banwords_html, bases_html, collect_html, prompt_html

router = Router()

MODE_CHAT = {0: "all", 1: "writers"}
MODE_CHAT_LABEL = {"all": "все участники", "writers": "только писавшие"}
MODE_DM = {0: "messaged", 1: "replied"}
MODE_DM_LABEL = {"messaged": "кому писали", "replied": "кто отвечал"}


async def _collect_screen():
    accounts = await ctx.store.list_accounts()
    return collect_html(accounts), collect_kb(accounts)


async def _settings_screen():
    words = await ctx.store.list_banwords()
    banned = await ctx.store.list_ban_contacts()
    return banwords_html(words, banned), banwords_kb(words)


async def _pick_account(account_id: int = 0):
    accounts = [a for a in await ctx.store.list_accounts() if a.has_telethon]
    if not accounts:
        return None
    if account_id:
        for a in accounts:
            if a.id == account_id:
                return a
        return None
    return accounts[0]


async def _save_result(result: CollectResult, base_name: str) -> tuple[int, int, int]:
    base = await ctx.store.add_base(base_name[:60])
    added = 0
    banned_n = 0
    for item in result.contacts:
        a, _ = await ctx.store.add_contacts([item], base.id)
        added += a
    for item in result.banned:
        reason = result.banned_reasons.get(f"{item.kind}:{item.value}", "banword")
        ok = await ctx.store.add_ban_contact(
            item.kind,
            item.value,
            display=item.display,
            reason=reason,
            source_base_id=base.id,
        )
        if ok:
            banned_n += 1
    return base.id, added, banned_n


@router.callback_query(MenuCB.filter(F.a == "collect"))
async def cb_collect(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _collect_screen()
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "col_set"))
@router.callback_query(MenuCB.filter(F.a == "banwords"))
async def cb_col_set(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _settings_screen()
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "col_mode"))
async def cb_col_mode(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    mode = MODE_CHAT.get(callback_data.i, "all")
    accounts = [a for a in await ctx.store.list_accounts() if a.has_telethon]
    if not accounts:
        await query.answer("Нет аккаунтов с session", show_alert=True)
        return
    await state.set_state(CollectChat.chat)
    await state.update_data(collect_mode=mode, account_id=0)
    text = prompt_html(
        "Ссылка на чат",
        f"Режим: <b>{MODE_CHAT_LABEL[mode]}</b>\n\n"
        "Пришлите ссылку или @username чата/группы.\n"
        f"Сбор пойдёт с любого доступного аккаунта "
        f"(сейчас: {len(accounts)}).\n\n"
        "Готовая база появится в «Базы» — её можно сразу запустить.",
        "users",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(CollectChat.chat, F.text)
async def on_col_chat(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    mode = data.get("collect_mode", "all")
    chat_ref = (message.text or "").strip()
    if not chat_ref:
        await message.answer("Пустая ссылка")
        return

    accounts = [a for a in await ctx.store.list_accounts() if a.has_telethon]
    if not accounts:
        await message.answer("Нет аккаунтов с session")
        return

    await message.answer(
        f"Собираю базу ({MODE_CHAT_LABEL.get(mode, mode)})…\n"
        "Это может занять время."
    )

    last_err = ""
    result = None
    used = None
    for acc in accounts:
        proxy = await ctx.store.peek_proxy(acc.id)
        try:
            async with telethon_client(acc.telethon_session, proxy) as client:
                result = await collect_from_chat(
                    client,
                    chat_ref,
                    mode=mode,
                    banwords=await ctx.store.list_banwords(),
                )
            used = acc
            break
        except Exception as e:
            last_err = str(e)
            continue

    if result is None or used is None:
        await message.answer(
            f"Не удалось собрать ни с одного аккаунта.\n"
            f"<code>{escape(last_err[:300])}</code>",
            parse_mode="HTML",
        )
        text, markup = await _collect_screen()
        await message.answer(text, reply_markup=markup, parse_mode="HTML")
        return

    title = result.chat_title or chat_ref
    label = MODE_CHAT_LABEL.get(mode, mode)
    base_id, added, _banned_n = await _save_result(
        result, f"{label}: {title}"
    )
    base = await ctx.store.get_base(base_id)
    body = (
        f"Чат: <code>{escape(chat_ref)}</code>\n"
        f"Режим: <b>{escape(label)}</b>\n"
        f"Аккаунт: <b>{escape(used.label)}</b>\n"
        f"В базу: <b>{added}</b> · банбаза: <b>{len(result.banned)}</b>\n"
        f"База: <b>{escape(base.name if base else '')}</b> <code>#{base_id}</code>\n\n"
        f"Можно открыть «Базы» и нажать Старт."
    )
    bases = await ctx.store.list_bases()
    stats = {b.id: await ctx.store.base_stats(b.id) for b in bases}
    await finish_input(
        message,
        prompt_html("Сбор готов", body, "check") + "\n\n" + bases_html(bases, stats),
        bases_kb(bases),
    )


@router.message(CollectChat.chat)
async def on_col_chat_bad(message: Message) -> None:
    await message.answer("Нужна текстовая ссылка или @username чата")


@router.callback_query(MenuCB.filter(F.a == "col_dm"))
async def cb_col_dm(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    mode = MODE_DM.get(callback_data.i, "messaged")
    accounts = await ctx.store.list_accounts()
    live = [a for a in accounts if a.has_telethon]
    if not live:
        await query.answer("Нет аккаунтов с session", show_alert=True)
        return
    await state.update_data(dm_mode=mode)
    text = prompt_html(
        "ЛС-история",
        f"Режим: <b>{MODE_DM_LABEL[mode]}</b>\n\n"
        "Выберите аккаунт, с которого собрать историю переписок.\n"
        "Или «Любой доступный» — возьмём первый с session.\n"
        "Результат сохранится <b>отдельной базой</b>.",
        "mega" if mode == "messaged" else "term",
    )
    await safe_edit(query, text, collect_accounts_kb(accounts, callback_data.i))


@router.callback_query(MenuCB.filter(F.a == "col_acc"))
async def cb_col_acc(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    mode = MODE_DM.get(callback_data.p, "messaged")
    data = await state.get_data()
    mode = data.get("dm_mode", mode)
    acc = await _pick_account(callback_data.i)
    if not acc:
        await query.answer("Нет аккаунта", show_alert=True)
        return
    await query.answer("Собираю…")
    await safe_edit(
        query,
        prompt_html(
            "Сбор ЛС",
            f"Аккаунт <b>{escape(acc.label)}</b>\n"
            f"Режим: <b>{MODE_DM_LABEL.get(mode, mode)}</b>\n"
            "Идёт обход диалогов…",
            "robot",
        ),
        None,
    )
    proxy = await ctx.store.peek_proxy(acc.id)
    try:
        async with telethon_client(acc.telethon_session, proxy) as client:
            result = await collect_dm_history(
                client,
                mode=mode,
                banwords=await ctx.store.list_banwords(),
            )
    except Exception as e:
        await safe_edit(
            query,
            prompt_html("Ошибка", escape(str(e)[:400]), "warn"),
            (await _collect_screen())[1],
        )
        return

    label = MODE_DM_LABEL.get(mode, mode)
    base_id, added, _banned_n = await _save_result(
        result, f"{label}: {acc.label}"
    )
    base = await ctx.store.get_base(base_id)
    body = (
        f"Режим: <b>{escape(label)}</b>\n"
        f"Аккаунт: <b>{escape(acc.label)}</b>\n"
        f"В базу: <b>{added}</b> · банбаза: <b>{len(result.banned)}</b>\n"
        f"База: <b>{escape(base.name if base else '')}</b> <code>#{base_id}</code>\n\n"
        f"Отдельная база готова к загрузке/старту."
    )
    bases = await ctx.store.list_bases()
    stats = {b.id: await ctx.store.base_stats(b.id) for b in bases}
    await safe_edit(
        query,
        prompt_html("Сбор готов", body, "check") + "\n\n" + bases_html(bases, stats),
        bases_kb(bases),
    )


@router.callback_query(MenuCB.filter(F.a == "bw_add"))
async def cb_bw_add(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BanwordsState.add)
    text = prompt_html(
        "Банворды",
        "Пришлите слова через запятую или с новой строки.\n"
        "При сборе базы: если в сообщениях пользователя есть эти слова — "
        "он уходит в банбазу, не в рассылку.",
        "warn",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(BanwordsState.add, F.text)
async def on_bw_add(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").replace(",", "\n")
    words = [w.strip() for w in raw.split("\n") if w.strip()]
    await state.clear()
    added, skipped = await ctx.store.add_banwords(words)
    text, markup = await _settings_screen()
    body = f"Добавлено: <b>{added}</b> · дубли: {skipped}"
    await finish_input(
        message,
        prompt_html("Банворды", body, "warn") + "\n\n" + text,
        markup,
    )


@router.callback_query(MenuCB.filter(F.a == "bw_del"))
async def cb_bw_del(query: CallbackQuery, callback_data: MenuCB) -> None:
    words = await ctx.store.list_banwords()
    idx = callback_data.i
    if idx < 0 or idx >= len(words):
        await query.answer("Нет слова")
        return
    await ctx.store.remove_banword(words[idx])
    await query.answer("Удалено")
    text, markup = await _settings_screen()
    await safe_edit(query, text, markup)
