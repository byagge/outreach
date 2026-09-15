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
    collect_chat_accounts_kb,
    collect_kb,
    collect_running_kb,
)
from app.bot.render import ask_input, finish_input, safe_edit
from app.bot.states import Banwords as BanwordsState
from app.bot.states import CollectChat
from app.context import ctx
from app.jobs.runtime import runtime
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
    running = runtime.is_running("collect", 0)
    return collect_html(accounts, running=running), collect_kb(accounts, running=running)


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


async def _save_result(
    result: CollectResult,
    base_name: str,
    *,
    kind: str,
    mode: str = "",
    target: str = "",
    account_id: int | None = None,
    source: str = "bot",
) -> tuple[int, int, int]:
    suffix = " (стоп)" if result.stopped else ""
    base = await ctx.store.add_base((base_name + suffix)[:60])
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
    await ctx.store.add_collect_run(
        source=source,
        kind=kind,
        mode=mode,
        target=target,
        title=result.chat_title or base.name,
        account_id=account_id,
        base_id=base.id,
        added=added,
        banned=banned_n,
        stopped=result.stopped,
        notes="; ".join(result.notes[:8]),
    )
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


@router.callback_query(MenuCB.filter(F.a == "col_stop"))
async def cb_col_stop(query: CallbackQuery) -> None:
    if not runtime.is_running("collect", 0):
        await query.answer("Сбор не идёт")
    else:
        runtime.request_cancel("collect", 0)
        await query.answer("Останавливаю — сохраню уже собранное…")
    text, markup = await _collect_screen()
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "col_final"))
async def cb_col_final(query: CallbackQuery, callback_data: MenuCB) -> None:
    """Итоговая база: без банвордов/blocklist/кому писали/дублей."""
    source = callback_data.i or None
    await query.answer("Собираю итоговую…")
    base, stats = await ctx.store.build_mailing_base(
        name="Итоговая рассылка",
        source_base_id=source,
    )
    await ctx.store.add_collect_run(
        source="bot",
        kind="mailing",
        mode="final",
        target=f"base:{source}" if source else "all",
        title=base.name,
        base_id=base.id,
        added=stats["added"],
        banned=0,
        notes=(
            f"ban={stats['excluded_ban']} block={stats['excluded_block']} "
            f"messaged={stats['excluded_messaged']} pending={stats['source_pending']}"
        ),
    )
    body = (
        f"База: <b>{escape(base.name)}</b> <code>#{base.id}</code>\n"
        f"Добавлено: <b>{stats['added']}</b>\n"
        f"Исключено банворды: {stats['excluded_ban']}\n"
        f"Исключено «не пишем»: {stats['excluded_block']}\n"
        f"Исключено «кому писали»/sent: {stats['excluded_messaged']}\n"
        f"Источник pending: {stats['source_pending']}\n\n"
        f"Можно сразу Старт. Смотрите в «История сбора»."
    )
    bases = await ctx.store.list_bases()
    st = {b.id: await ctx.store.base_stats(b.id) for b in bases}
    await safe_edit(
        query,
        prompt_html("Итоговая база", body, "check") + "\n\n" + bases_html(bases, st),
        bases_kb(bases),
    )


@router.callback_query(MenuCB.filter(F.a == "col_mode"))
async def cb_col_mode(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    if runtime.is_running("collect", 0):
        await query.answer("Сбор уже идёт — нажмите Стоп", show_alert=True)
        return
    mode = MODE_CHAT.get(callback_data.i, "all")
    accounts = await ctx.store.list_accounts()
    live = [a for a in accounts if a.has_telethon]
    if not live:
        await query.answer("Нет аккаунтов с session", show_alert=True)
        return
    await state.clear()
    await state.update_data(collect_mode=mode)
    text = prompt_html(
        "Чат для сбора",
        f"Режим: <b>{MODE_CHAT_LABEL[mode]}</b>\n\n"
        "Выберите аккаунт, который <b>уже состоит</b> в приватном чате "
        "(для id <code>-100…</code> это обязательно).\n"
        "Или «Все по очереди».",
        "users",
    )
    await safe_edit(query, text, collect_chat_accounts_kb(accounts, callback_data.i))


@router.callback_query(MenuCB.filter(F.a == "col_chat_acc"))
async def cb_col_chat_acc(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    if runtime.is_running("collect", 0):
        await query.answer("Сбор уже идёт", show_alert=True)
        return
    mode = MODE_CHAT.get(callback_data.p, "all")
    data = await state.get_data()
    mode = data.get("collect_mode", mode)
    account_id = callback_data.i
    if account_id:
        acc = await _pick_account(account_id)
        if not acc:
            await query.answer("Нет аккаунта", show_alert=True)
            return
        acc_note = f"Аккаунт: <b>{escape(acc.label)}</b>"
    else:
        acc_note = "Аккаунты: <b>все по очереди</b>"
    await state.set_state(CollectChat.chat)
    await state.update_data(collect_mode=mode, account_id=account_id)
    text = prompt_html(
        "Чат для сбора",
        f"Режим: <b>{MODE_CHAT_LABEL.get(mode, mode)}</b>\n"
        f"{acc_note}\n\n"
        "Пришлите:\n"
        "• ссылку / @username / invite\n"
        "• или id (<code>-100…</code>)\n\n"
        "Стоп во время сбора сохранит уже найденное.",
        "users",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(CollectChat.chat, F.text)
async def on_col_chat(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    mode = data.get("collect_mode", "all")
    account_id = int(data.get("account_id") or 0)
    chat_ref = (message.text or "").strip()
    if not chat_ref:
        await message.answer("Пустая ссылка")
        return
    if runtime.is_running("collect", 0):
        await message.answer("Сбор уже идёт")
        return

    accounts = [a for a in await ctx.store.list_accounts() if a.has_telethon]
    if account_id:
        accounts = [a for a in accounts if a.id == account_id]
    if not accounts:
        await message.answer("Нет аккаунтов с session")
        return

    status_msg = await message.answer(
        f"Собираю ({MODE_CHAT_LABEL.get(mode, mode)})…\n"
        "Можно нажать Стоп — сохраню прогресс.",
        reply_markup=collect_running_kb(),
        parse_mode="HTML",
    )

    async def job():
        last_err = ""
        result = None
        used = None
        banwords = await ctx.store.list_banwords()

        async def progress(msg: str) -> None:
            try:
                await status_msg.edit_text(
                    f"Собираю… {escape(msg)}\n"
                    f"Стоп — сохранить уже собранное.",
                    reply_markup=collect_running_kb(),
                    parse_mode="HTML",
                )
            except Exception:
                pass

        for acc in accounts:
            if runtime.cancelled("collect", 0):
                break
            proxy = await ctx.store.peek_proxy(acc.id)
            try:
                await progress(f"акк. {acc.label}: диалоги…")
                async with telethon_client(acc.telethon_session, proxy) as client:
                    result = await collect_from_chat(
                        client,
                        chat_ref,
                        mode=mode,
                        banwords=banwords,
                        should_stop=lambda: runtime.cancelled("collect", 0),
                        on_progress=progress,
                    )
                used = acc
                break
            except Exception as e:
                last_err = f"{acc.label}: {e}"
                continue

        if result is None or used is None:
            await message.answer(
                f"Не удалось собрать ни с одного аккаунта.\n"
                f"<code>{escape(last_err[:900])}</code>",
                parse_mode="HTML",
            )
            text, markup = await _collect_screen()
            await message.answer(text, reply_markup=markup, parse_mode="HTML")
            return

        if not result.contacts and not result.banned and result.stopped:
            await message.answer("Стоп: ещё ничего не собрано.")
            text, markup = await _collect_screen()
            await message.answer(text, reply_markup=markup, parse_mode="HTML")
            return

        title = result.chat_title or chat_ref
        label = MODE_CHAT_LABEL.get(mode, mode)
        base_id, added, _ = await _save_result(
            result,
            f"{label}: {title}",
            kind="chat",
            mode=mode,
            target=chat_ref,
            account_id=used.id,
        )
        base = await ctx.store.get_base(base_id)
        stop_note = " (остановка — сохранено частичное)" if result.stopped else ""
        body = (
            f"Чат: <code>{escape(chat_ref)}</code>{stop_note}\n"
            f"Режим: <b>{escape(label)}</b>\n"
            f"Аккаунт: <b>{escape(used.label)}</b>\n"
            f"В базу: <b>{added}</b> · банбаза: <b>{len(result.banned)}</b>\n"
            f"База: <b>{escape(base.name if base else '')}</b> <code>#{base_id}</code>\n\n"
            f"«Итоговая база» уберёт банворды / не пишем / кому писали."
        )
        bases = await ctx.store.list_bases()
        stats = {b.id: await ctx.store.base_stats(b.id) for b in bases}
        await message.answer(
            prompt_html("Сбор готов", body, "check") + "\n\n" + bases_html(bases, stats),
            reply_markup=bases_kb(bases),
            parse_mode="HTML",
        )

    try:
        runtime.spawn("collect", 0, job())
    except RuntimeError as e:
        await message.answer(str(e))


@router.message(CollectChat.chat)
async def on_col_chat_bad(message: Message) -> None:
    await message.answer("Нужна текстовая ссылка, @username или id (-100…)")


@router.callback_query(MenuCB.filter(F.a == "col_dm"))
async def cb_col_dm(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    if runtime.is_running("collect", 0):
        await query.answer("Сбор уже идёт", show_alert=True)
        return
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
        "Выберите аккаунт. Результат — отдельная база.\n"
        "Во время сбора доступен Стоп.",
        "mega" if mode == "messaged" else "term",
    )
    await safe_edit(query, text, collect_accounts_kb(accounts, callback_data.i))


@router.callback_query(MenuCB.filter(F.a == "col_acc"))
async def cb_col_acc(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    if runtime.is_running("collect", 0):
        await query.answer("Сбор уже идёт", show_alert=True)
        return
    mode = MODE_DM.get(callback_data.p, "messaged")
    data = await state.get_data()
    mode = data.get("dm_mode", mode)
    await state.clear()
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
            "Стоп сохранит уже найденное.",
            "robot",
        ),
        collect_running_kb(),
    )

    async def job():
        proxy = await ctx.store.peek_proxy(acc.id)
        try:
            async with telethon_client(acc.telethon_session, proxy) as client:
                result = await collect_dm_history(
                    client,
                    mode=mode,
                    banwords=await ctx.store.list_banwords(),
                    should_stop=lambda: runtime.cancelled("collect", 0),
                )
        except Exception as e:
            await query.message.answer(
                prompt_html("Ошибка", escape(str(e)[:400]), "warn"),
                parse_mode="HTML",
            )
            return

        label = MODE_DM_LABEL.get(mode, mode)
        base_id, added, _ = await _save_result(
            result,
            f"{label}: {acc.label}",
            kind="dm",
            mode=mode,
            target=acc.label,
            account_id=acc.id,
        )
        base = await ctx.store.get_base(base_id)
        stop_note = " (стоп)" if result.stopped else ""
        body = (
            f"Режим: <b>{escape(label)}</b>{stop_note}\n"
            f"Аккаунт: <b>{escape(acc.label)}</b>\n"
            f"В базу: <b>{added}</b> · банбаза: <b>{len(result.banned)}</b>\n"
            f"База: <b>{escape(base.name if base else '')}</b> <code>#{base_id}</code>"
        )
        bases = await ctx.store.list_bases()
        stats = {b.id: await ctx.store.base_stats(b.id) for b in bases}
        await query.message.answer(
            prompt_html("Сбор готов", body, "check") + "\n\n" + bases_html(bases, stats),
            reply_markup=bases_kb(bases),
            parse_mode="HTML",
        )

    try:
        runtime.spawn("collect", 0, job())
    except RuntimeError as e:
        await query.answer(str(e), show_alert=True)


@router.callback_query(MenuCB.filter(F.a == "col_hist"))
async def cb_col_hist(query: CallbackQuery, callback_data: MenuCB) -> None:
    page = max(0, callback_data.p)
    runs = await ctx.store.list_collect_runs(limit=10, offset=page * 10)
    from app.bot.keyboards import collect_history_kb
    from app.ui.screens import collect_history_html

    await safe_edit(
        query,
        collect_history_html(runs, page=page),
        collect_history_kb(runs, page=page),
    )


@router.callback_query(MenuCB.filter(F.a == "col_run"))
async def cb_col_run(query: CallbackQuery, callback_data: MenuCB) -> None:
    run = await ctx.store.get_collect_run(callback_data.i)
    if not run:
        await query.answer("Нет записи", show_alert=True)
        return
    from app.bot.keyboards import collect_run_kb
    from app.ui.screens import collect_run_html

    await safe_edit(query, collect_run_html(run), collect_run_kb(run))


@router.callback_query(MenuCB.filter(F.a == "col_dl"))
async def cb_col_dl(query: CallbackQuery, callback_data: MenuCB) -> None:
    run = await ctx.store.get_collect_run(callback_data.i)
    if not run or not run.base_id:
        await query.answer("Нет базы у этой записи", show_alert=True)
        return
    contacts = await ctx.store.export_contacts(run.base_id)
    if not contacts:
        await query.answer("База пустая", show_alert=True)
        return
    from aiogram.types import BufferedInputFile

    from app.utils.export import contacts_to_csv, contacts_to_txt, contacts_to_xlsx

    safe = (run.base_name or run.title or f"collect_{run.id}").replace(" ", "_")[:30]
    for ext, data in (
        ("txt", contacts_to_txt(contacts)),
        ("csv", contacts_to_csv(contacts)),
        ("xlsx", contacts_to_xlsx(contacts)),
    ):
        await query.message.answer_document(
            BufferedInputFile(data, filename=f"{safe}.{ext}"),
        )
    await query.answer(f"Скачано {len(contacts)} контактов")


@router.callback_query(MenuCB.filter(F.a == "bw_add"))
async def cb_bw_add(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BanwordsState.add)
    text = prompt_html(
        "Банворды",
        "Пришлите слова через запятую или с новой строки.\n"
        "При сборе: совпадение → банбаза, не в рассылку.",
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
