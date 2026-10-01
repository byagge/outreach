from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import (
    MenuCB,
    assign_campaign_kb,
    bases_kb,
    banbase_kb,
    banwords_kb,
    cancel_kb,
    collect_accounts_kb,
    collect_chat_accounts_kb,
    collect_done_kb,
    collect_kb,
    collect_premium_accounts_kb,
    collect_premium_done_kb,
    collect_premium_lang_kb,
    collect_running_kb,
    collect_separate_kb,
    confirm_kb,
)
from app.bot.render import ask_input, finish_input, safe_edit
from app.bot.states import Banwords as BanwordsState
from app.bot.states import CollectChat
from app.config import get_settings
from app.context import ctx
from app.jobs.runtime import runtime
from app.tg.client import telethon_client
from app.tg.collect import (
    CollectResult,
    PremiumCollectResult,
    collect_dm_history,
    collect_from_chat,
)
from app.tg.premium_collect import collect_premium_from_groups
from app.ui.screens import (
    banbase_html,
    banwords_html,
    bases_html,
    collect_html,
    collect_premium_html,
    collect_separate_html,
    prompt_html,
)

router = Router()

MODE_CHAT = {0: "all", 1: "writers"}
MODE_CHAT_LABEL = {"all": "все участники", "writers": "только писавшие"}
MODE_DM = {0: "messaged", 1: "replied"}
MODE_DM_LABEL = {"messaged": "кому писали", "replied": "кто отвечал"}
PREM_LANG = {0: "ru", 1: "en"}
PREM_LANG_LABEL = {"ru": "русский", "en": "english"}


async def _collect_screen():
    accounts = await ctx.store.list_accounts()
    running = runtime.is_running("collect", 0)
    return collect_html(accounts, running=running), collect_kb(accounts, running=running)


async def _save_premium_result(
    result: PremiumCollectResult,
    *,
    language: str,
    account_id: int,
    account_label: str,
    source: str = "bot",
) -> dict[str, int]:
    """Три isolated-базы + journal. premium enabled=1 как основная ценность."""
    stamp = account_label[:20]
    lang = PREM_LANG_LABEL.get(language, language)
    suffix = " (стоп)" if result.stopped else ""

    async def _one(name: str, items: list, *, enabled: int) -> tuple[int, int]:
        base = await ctx.store.add_base(
            (name + suffix)[:60],
            isolated=1,
            enabled=enabled,
        )
        added = 0
        for item in items:
            a, _ = await ctx.store.add_contacts([item], base.id)
            added += a
        return base.id, added

    prem_id, prem_n = await _one(
        f"★ Дорогие [{lang}]: {stamp}",
        result.premium,
        enabled=1,
    )
    cod_id, cod_n = await _one(
        f"Кодеры [{lang}]: {stamp}",
        result.coders,
        enabled=0,
    )
    oth_id, oth_n = await _one(
        f"Прочие [{lang}]: {stamp}",
        result.other,
        enabled=0,
    )

    banned_n = 0
    for item in result.banned:
        reason = result.banned_reasons.get(f"{item.kind}:{item.value}", "banword")
        ok = await ctx.store.add_ban_contact(
            item.kind,
            item.value,
            display=item.display,
            reason=reason,
            source_base_id=prem_id,
        )
        if ok:
            banned_n += 1

    await ctx.store.add_collect_run(
        source=source,
        kind="premium",
        mode=f"lang:{language}",
        target=account_label,
        title=f"★ {prem_n} / код {cod_n} / др {oth_n}",
        account_id=account_id,
        base_id=prem_id,
        added=prem_n + cod_n + oth_n,
        banned=banned_n,
        stopped=result.stopped,
        notes="; ".join(result.notes[:8])
        + f"; bases={prem_id},{cod_id},{oth_id}",
    )
    return {
        "premium_id": prem_id,
        "coders_id": cod_id,
        "other_id": oth_id,
        "premium_n": prem_n,
        "coders_n": cod_n,
        "other_n": oth_n,
        "banned_n": banned_n,
    }


async def _settings_screen(page: int = 0):
    words = await ctx.store.list_banwords()
    banned_total = await ctx.store.count_ban_contacts()
    return (
        banwords_html(words, banned_total=banned_total, page=page),
        banwords_kb(words, page=page, banned_total=banned_total),
    )


async def _banbase_screen(page: int = 0):
    per = 10
    total = await ctx.store.count_ban_contacts()
    pages = max(1, (total + per - 1) // per)
    page = max(0, min(page, pages - 1))
    items = await ctx.store.list_ban_contacts(page=page, per_page=per)
    return banbase_html(items, total, page=page, per=per), banbase_kb(items, total, page=page, per=per)


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
    separate: bool = False,
) -> tuple[int, int, int]:
    suffix = " (стоп)" if result.stopped else ""
    prefix = "⊕ " if separate else ""
    base = await ctx.store.add_base(
        (prefix + base_name + suffix)[:60],
        isolated=1 if separate else 0,
        enabled=0 if separate else 1,
    )
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
        mode=("separate:" + mode) if separate and mode else ("separate" if separate else mode),
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


async def _done_message(
    message: Message,
    *,
    body: str,
    base_id: int,
    separate: bool,
) -> None:
    markup = collect_done_kb(base_id, separate=separate)
    await message.answer(
        prompt_html("Сбор готов", body, "check"),
        reply_markup=markup,
        parse_mode="HTML",
    )


@router.callback_query(MenuCB.filter(F.a == "collect"))
async def cb_collect(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _collect_screen()
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "col_prem"))
async def cb_col_prem(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if runtime.is_running("collect", 0):
        await query.answer("Сбор уже идёт — Стоп", show_alert=True)
        return
    await safe_edit(query, collect_premium_html(), collect_premium_lang_kb())


@router.callback_query(MenuCB.filter(F.a == "col_plang"))
async def cb_col_plang(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    if runtime.is_running("collect", 0):
        await query.answer("Сбор уже идёт", show_alert=True)
        return
    lang = PREM_LANG.get(callback_data.i, "ru")
    accounts = await ctx.store.list_accounts()
    live = [a for a in accounts if a.has_telethon]
    if not live:
        await query.answer("Нет аккаунтов с session", show_alert=True)
        return
    await state.update_data(prem_lang=lang)
    from app.ai.llm import llm_configured

    cfg = get_settings()
    if not llm_configured():
        await safe_edit(
            query,
            prompt_html(
                "Нужен LLM",
                "Для смыслового отбора нужен API:\n"
                "• OpenAI-compatible <code>claude-opus-5-5</code>\n"
                "• Bardborn / OpenAI / Anthropic / OpenRouter\n"
                "В <code>.env</code>:\n"
                "<code>LLM_ENABLED=true</code>\n"
                "<code>LLM_BASE_URL=...</code>\n"
                "<code>LLM_API_KEY=...</code>\n"
                "<code>LLM_MODEL=...</code>",
                "warn",
            ),
            collect_premium_lang_kb(),
        )
        return
    llm_note = f"LLM: <code>{escape(cfg.llm_model)}</code>"
    disc = (
        f"Поиск открытых: до {cfg.premium_discover_join_max} join"
        if cfg.premium_discover_open
        else "Поиск открытых: выкл"
    )
    text = prompt_html(
        "Дорогие контакты",
        f"Язык: <b>{PREM_LANG_LABEL[lang]}</b>\n"
        f"{llm_note}\n"
        f"{disc}\n\n"
        "ИИ читает смысл постов (не ключи).\n"
        "Выберите аккаунт:",
        "crown",
    )
    await safe_edit(query, text, collect_premium_accounts_kb(accounts, callback_data.i))


@router.callback_query(MenuCB.filter(F.a == "col_pacc"))
async def cb_col_pacc(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    if runtime.is_running("collect", 0):
        await query.answer("Сбор уже идёт", show_alert=True)
        return
    lang = PREM_LANG.get(callback_data.p, "ru")
    data = await state.get_data()
    lang = data.get("prem_lang", lang)
    await state.clear()
    acc = await _pick_account(callback_data.i)
    if not acc:
        await query.answer("Нет аккаунта", show_alert=True)
        return
    await query.answer("Старт…")
    cfg = get_settings()
    from app.ai.llm import llm_configured

    if not llm_configured():
        await safe_edit(
            query,
            prompt_html(
                "Нужен LLM",
                "Заполните LLM_* в .env (bardborn / OpenAI / OpenRouter).",
                "warn",
            ),
            collect_premium_lang_kb(),
        )
        return
    await safe_edit(
        query,
        prompt_html(
            "Дорогие контакты",
            f"Аккаунт <b>{escape(acc.label)}</b>\n"
            f"Язык: <b>{PREM_LANG_LABEL.get(lang, lang)}</b>\n"
            f"Модель: <code>{escape(cfg.llm_model)}</code>\n"
            f"ИИ читает смысл всех постов…\n"
            "Стоп сохранит уже найденное.",
            "crown",
        ),
        collect_running_kb(),
    )

    async def job():
        proxy = await ctx.store.peek_proxy(acc.id)
        status = query.message

        async def progress(msg: str) -> None:
            try:
                await status.edit_text(
                    prompt_html(
                        "Дорогие контакты",
                        f"{escape(msg)}\nСтоп — сохранить прогресс.",
                        "crown",
                    ),
                    reply_markup=collect_running_kb(),
                    parse_mode="HTML",
                )
            except Exception:
                pass

        try:
            async with telethon_client(acc.telethon_session, proxy) as client:
                result = await collect_premium_from_groups(
                    client,
                    language=lang,
                    banwords=await ctx.store.list_banwords(),
                    messages_per_chat=int(cfg.premium_messages_per_chat),
                    max_msgs_per_user=int(cfg.premium_max_msgs_per_user),
                    llm_base_url=cfg.llm_base_url,
                    llm_model=cfg.llm_model,
                    llm_api_key=cfg.llm_api_key,
                    llm_model_refine=cfg.llm_model_refine,
                    use_llm=True,
                    discover_open=bool(cfg.premium_discover_open),
                    max_discover_join=int(cfg.premium_discover_join_max),
                    premium_threshold=int(cfg.premium_score_threshold),
                    chat_min_score=int(cfg.premium_chat_min_score),
                    chat_top_k=int(cfg.premium_chat_top_k),
                    batch_size=int(cfg.llm_batch_size),
                    max_posts_to_llm=int(cfg.llm_max_posts),
                    scan_all_chats=bool(cfg.premium_scan_all_chats),
                    should_stop=lambda: runtime.cancelled("collect", 0),
                    on_progress=progress,
                )
        except Exception as e:
            await query.message.answer(
                prompt_html("Ошибка", escape(str(e)[:500]), "warn"),
                parse_mode="HTML",
            )
            text, markup = await _collect_screen()
            await query.message.answer(text, reply_markup=markup, parse_mode="HTML")
            return

        if (
            not result.premium
            and not result.coders
            and not result.other
            and not result.banned
        ):
            await query.message.answer(
                prompt_html(
                    "Пусто",
                    "Не нашли ★ чаты / писавших"
                    + (" (стоп)" if result.stopped else "")
                    + f".\n{escape('; '.join(result.notes[:5]))}",
                    "warn",
                ),
                parse_mode="HTML",
            )
            text, markup = await _collect_screen()
            await query.message.answer(text, reply_markup=markup, parse_mode="HTML")
            return

        ids = await _save_premium_result(
            result,
            language=lang,
            account_id=acc.id,
            account_label=acc.label,
        )
        stop_note = " (стоп — частичное)" if result.stopped else ""
        from app.ui.emoji import pe

        titles = ", ".join(escape(t)[:28] for t in result.premium_chat_titles[:5])
        more = (
            f" +{len(result.premium_chat_titles) - 5}"
            if len(result.premium_chat_titles) > 5
            else ""
        )
        body = (
            f"Аккаунт: <b>{escape(acc.label)}</b>{stop_note}\n"
            f"Язык: <b>{PREM_LANG_LABEL.get(lang, lang)}</b>\n"
            f"★ чатов: <b>{result.chats_premium}</b> · "
            f"пропущено: {result.chats_skipped} · "
            f"join: {result.chats_joined}\n"
            f"Глубокий скан: <b>{result.chats_scanned}</b>\n"
            f"{('Чаты: ' + titles + more + chr(10)) if titles else ''}"
            f"\n{pe('crown')} <b>★ Дорогие:</b> {ids['premium_n']} "
            f"<code>#{ids['premium_id']}</code>\n"
            f"Кодеры: {ids['coders_n']} <code>#{ids['coders_id']}</code>\n"
            f"Прочие: {ids['other_n']} <code>#{ids['other_id']}</code>\n"
            f"Банбаза: {ids['banned_n']}"
        )
        await query.message.answer(
            prompt_html("Сбор дорогих готов", body, "crown"),
            reply_markup=collect_premium_done_kb(
                ids["premium_id"], ids["coders_id"], ids["other_id"]
            ),
            parse_mode="HTML",
        )

    try:
        runtime.spawn("collect", 0, job())
    except RuntimeError as e:
        await query.answer(str(e), show_alert=True)


@router.callback_query(MenuCB.filter(F.a == "col_sep"))
async def cb_col_sep(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(collect_separate=True)
    await safe_edit(query, collect_separate_html(), collect_separate_kb())


@router.callback_query(MenuCB.filter(F.a == "col_set"))
@router.callback_query(MenuCB.filter(F.a == "banwords"))
async def cb_col_set(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _settings_screen(page=callback_data.p)
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "bw_page"))
async def cb_bw_page(query: CallbackQuery, callback_data: MenuCB) -> None:
    text, markup = await _settings_screen(page=max(0, callback_data.p))
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "bw_all"))
async def cb_bw_all(query: CallbackQuery) -> None:
    words = await ctx.store.list_banwords()
    if not words:
        await query.answer("Список пуст", show_alert=True)
        return
    from aiogram.types import BufferedInputFile

    body = "\n".join(words)
    await query.message.answer_document(
        BufferedInputFile(body.encode("utf-8"), filename="banwords.txt"),
        caption=f"Банворды: {len(words)}",
    )
    await query.answer()


@router.callback_query(MenuCB.filter(F.a == "bb_view"))
@router.callback_query(MenuCB.filter(F.a == "bb_page"))
async def cb_bb_view(query: CallbackQuery, callback_data: MenuCB) -> None:
    text, markup = await _banbase_screen(page=max(0, callback_data.p))
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "bb_del"))
async def cb_bb_del(query: CallbackQuery, callback_data: MenuCB) -> None:
    ok = await ctx.store.remove_ban_contact(callback_data.i)
    await query.answer("Удалено" if ok else "Уже нет")
    text, markup = await _banbase_screen(page=max(0, callback_data.p))
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "bb_clr"))
async def cb_bb_clr(query: CallbackQuery) -> None:
    total = await ctx.store.count_ban_contacts()
    await safe_edit(
        query,
        prompt_html(
            "Очистить банбазу",
            f"Удалить все <b>{total}</b> записей из банбазы?\n"
            "Банворды (слова) не трогаются.",
            "warn",
        ),
        confirm_kb(
            MenuCB(a="bb_clr2"),
            MenuCB(a="bb_view"),
            yes_text="Очистить всё",
        ),
    )


@router.callback_query(MenuCB.filter(F.a == "bb_clr2"))
async def cb_bb_clr2(query: CallbackQuery) -> None:
    n = await ctx.store.clear_ban_contacts()
    await query.answer(f"Удалено {n}")
    text, markup = await _banbase_screen(0)
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
    data = await state.get_data()
    separate = bool(data.get("collect_separate"))
    accounts = await ctx.store.list_accounts()
    live = [a for a in accounts if a.has_telethon]
    if not live:
        await query.answer("Нет аккаунтов с session", show_alert=True)
        return
    await state.update_data(collect_mode=mode, collect_separate=separate)
    sep_note = "\nРежим: <b>отдельная база</b> (не в основной очереди)." if separate else ""
    text = prompt_html(
        "Чат для сбора",
        f"Режим: <b>{MODE_CHAT_LABEL[mode]}</b>{sep_note}\n\n"
        "Выберите аккаунт, который <b>уже состоит</b> в приватном чате "
        "(для id <code>-100…</code> это обязательно).\n"
        "Или «Все по очереди».",
        "folder" if separate else "users",
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
    separate = bool(data.get("collect_separate"))
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
    await state.update_data(
        collect_mode=mode, account_id=account_id, collect_separate=separate
    )
    sep_note = "\nБаза: <b>отдельная</b>." if separate else ""
    text = prompt_html(
        "Чат для сбора",
        f"Режим: <b>{MODE_CHAT_LABEL.get(mode, mode)}</b>\n"
        f"{acc_note}{sep_note}\n\n"
        "Пришлите:\n"
        "• ссылку / @username / invite\n"
        "• или id (<code>-100…</code>)\n\n"
        "Стоп во время сбора сохранит уже найденное.",
        "folder" if separate else "users",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(CollectChat.chat, F.text)
async def on_col_chat(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    mode = data.get("collect_mode", "all")
    account_id = int(data.get("account_id") or 0)
    separate = bool(data.get("collect_separate"))
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
        f"Собираю ({MODE_CHAT_LABEL.get(mode, mode)})"
        f"{' · отдельно' if separate else ''}…\n"
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
            separate=separate,
        )
        base = await ctx.store.get_base(base_id)
        stop_note = " (остановка — сохранено частичное)" if result.stopped else ""
        sep_note = "\nТип: <b>отдельная</b> — не в основной очереди." if separate else ""
        body = (
            f"Чат: <code>{escape(chat_ref)}</code>{stop_note}\n"
            f"Режим: <b>{escape(label)}</b>\n"
            f"Аккаунт: <b>{escape(used.label)}</b>\n"
            f"В базу: <b>{added}</b> · банбаза: <b>{len(result.banned)}</b>\n"
            f"База: <b>{escape(base.name if base else '')}</b> <code>#{base_id}</code>"
            f"{sep_note}"
        )
        await _done_message(message, body=body, base_id=base_id, separate=separate)

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
    data = await state.get_data()
    separate = bool(data.get("collect_separate"))
    mode = MODE_DM.get(callback_data.i, "messaged")
    accounts = await ctx.store.list_accounts()
    live = [a for a in accounts if a.has_telethon]
    if not live:
        await query.answer("Нет аккаунтов с session", show_alert=True)
        return
    await state.update_data(dm_mode=mode, collect_separate=separate)
    sep_note = "\nБаза будет <b>отдельной</b>." if separate else ""
    text = prompt_html(
        "ЛС-история",
        f"Режим: <b>{MODE_DM_LABEL[mode]}</b>{sep_note}\n\n"
        "Выберите аккаунт. Результат — отдельная база.\n"
        "Во время сбора доступен Стоп.",
        "folder" if separate else ("mega" if mode == "messaged" else "term"),
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
    separate = bool(data.get("collect_separate"))
    await state.clear()
    acc = await _pick_account(callback_data.i)
    if not acc:
        await query.answer("Нет аккаунта", show_alert=True)
        return
    await query.answer("Собираю…")
    sep_line = "Отдельная база.\n" if separate else ""
    await safe_edit(
        query,
        prompt_html(
            "Сбор ЛС",
            f"Аккаунт <b>{escape(acc.label)}</b>\n"
            f"Режим: <b>{MODE_DM_LABEL.get(mode, mode)}</b>\n"
            f"{sep_line}"
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
            separate=separate,
        )
        base = await ctx.store.get_base(base_id)
        stop_note = " (стоп)" if result.stopped else ""
        sep_note = "\nТип: <b>отдельная</b>." if separate else ""
        body = (
            f"Режим: <b>{escape(label)}</b>{stop_note}\n"
            f"Аккаунт: <b>{escape(acc.label)}</b>\n"
            f"В базу: <b>{added}</b> · банбаза: <b>{len(result.banned)}</b>\n"
            f"База: <b>{escape(base.name if base else '')}</b> <code>#{base_id}</code>"
            f"{sep_note}"
        )
        await _done_message(query.message, body=body, base_id=base_id, separate=separate)

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


@router.callback_query(MenuCB.filter(F.a == "col_exp"))
async def cb_col_exp(query: CallbackQuery, callback_data: MenuCB) -> None:
    base_id = callback_data.i
    base = await ctx.store.get_base(base_id)
    if not base:
        await query.answer("Нет базы", show_alert=True)
        return
    contacts = await ctx.store.export_contacts(base_id)
    if not contacts:
        await query.answer("База пустая", show_alert=True)
        return
    from aiogram.types import BufferedInputFile

    from app.utils.export import contacts_to_csv, contacts_to_txt, contacts_to_xlsx

    safe = (base.name or f"base_{base_id}").replace(" ", "_")[:30]
    for ext, data in (
        ("txt", contacts_to_txt(contacts)),
        ("csv", contacts_to_csv(contacts)),
        ("xlsx", contacts_to_xlsx(contacts)),
    ):
        await query.message.answer_document(
            BufferedInputFile(data, filename=f"{safe}.{ext}"),
        )
    await query.answer(f"Скачано {len(contacts)}")
    await safe_edit(
        query,
        prompt_html(
            "Экспорт",
            f"База <b>{escape(base.name)}</b> · {len(contacts)} контактов.\n"
            f"{'Отдельная — можно назначить в кампанию.' if base.isolated else ''}",
            "up",
        ),
        collect_done_kb(base_id, separate=bool(base.isolated)),
    )


@router.callback_query(MenuCB.filter(F.a == "asg_camp"))
async def cb_asg_camp(query: CallbackQuery, callback_data: MenuCB) -> None:
    base = await ctx.store.get_base(callback_data.i)
    if not base:
        await query.answer("Нет базы", show_alert=True)
        return
    camps = await ctx.store.list_campaigns()
    await safe_edit(
        query,
        prompt_html(
            "Назначить базу",
            f"База <b>{escape(base.name)}</b> <code>#{base.id}</code>\n\n"
            f"Выберите кампанию:\n"
            f"• <b>Основной</b> — включит базу в общую рассылку\n"
            f"• другая — привяжет только к этой кампании",
            "check",
        ),
        assign_campaign_kb(camps, base.id),
    )


@router.callback_query(MenuCB.filter(F.a == "asg_do"))
async def cb_asg_do(query: CallbackQuery, callback_data: MenuCB) -> None:
    base_id = callback_data.i
    campaign_id = callback_data.p
    msg = await ctx.store.assign_base_to_campaign(base_id, campaign_id)
    await query.answer("Назначено")
    base = await ctx.store.get_base(base_id)
    await safe_edit(
        query,
        prompt_html("Назначено", escape(msg), "check"),
        collect_done_kb(base_id, separate=bool(base and base.isolated)),
    )


@router.callback_query(MenuCB.filter(F.a == "bw_add"))
async def cb_bw_add(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BanwordsState.add)
    text = prompt_html(
        "Банворды",
        "Пришлите слова через запятую или с новой строки.\n"
        "Минимум <b>3 символа</b> на слово (<code>r</code>/<code>c</code> не принимаются).\n"
        "Матч — целое слово/фраза в сообщении → банбаза.",
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
    body = (
        f"Добавлено: <b>{added}</b> · пропущено (дубли / &lt;3 символов): {skipped}"
    )
    await finish_input(
        message,
        prompt_html("Банворды", body, "warn") + "\n\n" + text,
        markup,
    )


@router.callback_query(MenuCB.filter(F.a == "bw_del"))
async def cb_bw_del(query: CallbackQuery, callback_data: MenuCB) -> None:
    words = await ctx.store.list_banwords()
    idx = callback_data.i
    page = callback_data.p
    if idx < 0 or idx >= len(words):
        await query.answer("Нет слова")
        return
    await ctx.store.remove_banword(words[idx])
    await query.answer("Удалено")
    text, markup = await _settings_screen(page=page)
    await safe_edit(query, text, markup)
