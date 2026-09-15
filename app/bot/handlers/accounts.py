from __future__ import annotations

from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import MenuCB, account_kb, accounts_kb, cancel_kb, confirm_kb
from app.bot.render import ask_input, finish_input, safe_edit
from app.ai.contacts import parse_lines
from app.bot.states import AccountFile, AccountSettings, AddAccount
from app.config import SESSIONS_DIR
from app.context import ctx
from app.tg.client import inspect_session
from app.ui.screens import account_html, accounts_html, prompt_html
from app.utils.sessions import detect_session_kind
from app.utils.work_hours import parse_work_hours

router = Router()


async def _payload(acc):
    proxies = await ctx.store.proxies_for_account(acc.id)
    return account_html(acc, proxies), account_kb(acc)


@router.callback_query(MenuCB.filter(F.a == "accounts"))
async def cb_accounts(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    accounts = await ctx.store.list_accounts()
    await safe_edit(query, accounts_html(accounts), accounts_kb(accounts, callback_data.p))


@router.callback_query(MenuCB.filter(F.a == "acc"))
async def cb_acc(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    acc = await ctx.store.get_account(callback_data.i)
    if not acc:
        await query.answer("Нет аккаунта", show_alert=True)
        return
    text, markup = await _payload(acc)
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "acc_asg"))
async def cb_asg(query: CallbackQuery, callback_data: MenuCB) -> None:
    acc = await ctx.store.toggle_assigned(callback_data.i)
    if not acc:
        await query.answer("Нет аккаунта", show_alert=True)
        return
    await query.answer("Назначен" if acc.assigned else "Снят")
    text, markup = await _payload(acc)
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "acc_add"))
async def cb_acc_add(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddAccount.session)
    await safe_edit(
        query,
        prompt_html(
            "Добавить аккаунт",
            "Пришлите файл <b>.session</b> (Telethon).\n"
            "Прокси подхватятся сами, аккаунт сразу назначен на рассылку.",
            "lock",
        ),
        cancel_kb(),
    )
    await ask_input(query, prompt_html("Файл", "Жду <b>.session</b>", "inbox"))


@router.message(AddAccount.session, F.document)
async def on_new_session(message: Message, state: FSMContext) -> None:
    doc = message.document
    if not doc or not (doc.file_name or "").lower().endswith(".session"):
        await message.answer("Нужен файл с расширением .session")
        return
    tmp = SESSIONS_DIR / f"_upload_{doc.file_unique_id}.session"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    await message.bot.download(doc, destination=tmp)
    kind = detect_session_kind(tmp)
    if kind == "pyrogram":
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        await message.answer("Это Pyrogram session. Нужен Telethon .session")
        return
    await state.update_data(tmp=str(tmp), filename=doc.file_name or "account.session")
    await state.set_state(AddAccount.label)
    await ask_input(
        message,
        prompt_html("Имя", f"Файл принят (<code>{kind}</code>).\nИмя аккаунта:"),
    )


@router.message(AddAccount.label, F.text)
async def on_new_label(message: Message, state: FSMContext) -> None:
    label = (message.text or "").strip()
    if not label:
        await message.answer("Пустое имя")
        return
    data = await state.get_data()
    tmp = Path(data["tmp"])
    acc = await ctx.store.add_account(label)
    dest_dir = SESSIONS_DIR / str(acc.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "telethon.session"
    dest.write_bytes(tmp.read_bytes())
    fields = {"telethon_session": str(dest)}
    proxy = None
    bound = await ctx.store.proxies_for_account(acc.id)
    if bound:
        proxy = bound[0]
    try:
        info = await inspect_session(dest, proxy)
        fields.update(
            user_id=info["user_id"],
            username=info["username"],
            phone=info["phone"],
        )
        note = f"Telethon: вошли как {info['first_name']} (@{info['username'] or '-'})"
    except Exception as e:
        note = f"Session сохранена, но не удалось открыть: {e}"
    await ctx.store.update_account(acc.id, **fields)
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    await state.clear()
    acc = await ctx.store.get_account(acc.id)
    from html import escape as _esc

    if not acc:
        await message.answer("Аккаунт не найден")
        return
    text, markup = await _payload(acc)
    await finish_input(message, f"{_esc(note)}\n\n{text}", markup)


@router.callback_query(MenuCB.filter(F.a == "acc_tl"))
async def cb_acc_file(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.update_data(account_id=callback_data.i)
    await state.set_state(AccountFile.telethon)
    await safe_edit(
        query,
        prompt_html("Session", "Пришлите <b>Telethon</b> .session для этого аккаунта.", "lock"),
        cancel_kb(),
    )
    await ask_input(query, prompt_html("Файл", "Жду <b>.session</b>", "inbox"))


@router.message(AccountFile.telethon, F.document)
async def on_tl(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    account_id = data.get("account_id")
    if not account_id:
        await message.answer("Сессия ввода сброшена. Откройте аккаунт снова.")
        return
    acc = await ctx.store.get_account(int(account_id))
    if not acc:
        await message.answer("Аккаунт не найден")
        return
    dest_dir = SESSIONS_DIR / str(acc.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "telethon.session"
    await message.bot.download(message.document, destination=dest)
    fields = {"telethon_session": str(dest)}
    extra = ""
    proxy = (await ctx.store.proxies_for_account(acc.id) or [None])[0]
    try:
        info = await inspect_session(dest, proxy)
        fields.update(
            user_id=info["user_id"],
            username=info["username"],
            phone=info["phone"],
        )
        extra = f"\nВошли: {info['first_name']} (@{info['username'] or '-'})"
    except Exception as e:
        extra = f"\nНе открылась: {e}"
    await ctx.store.update_account(acc.id, **fields)
    acc = await ctx.store.get_account(acc.id)
    from html import escape as _esc

    text, markup = await _payload(acc)
    await finish_input(message, text + _esc(extra), markup)


@router.callback_query(MenuCB.filter(F.a == "acc_ren"))
async def cb_ren(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.set_state(AccountFile.rename)
    await state.update_data(account_id=callback_data.i)
    await safe_edit(query, prompt_html("Имя", "Новое имя аккаунта:"), cancel_kb())
    await ask_input(query, prompt_html("Имя", "Жду имя"))


@router.message(AccountFile.rename, F.text)
async def on_ren(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    acc = await ctx.store.update_account(int(data["account_id"]), label=(message.text or "").strip())
    if not acc:
        await message.answer("Аккаунт не найден")
        return
    text, markup = await _payload(acc)
    await finish_input(message, text, markup)


@router.callback_query(MenuCB.filter(F.a == "acc_del"))
async def cb_del(query: CallbackQuery, callback_data: MenuCB) -> None:
    await safe_edit(
        query,
        prompt_html("Удалить", "Удалить аккаунт из системы? Session на диске останется.", "warn"),
        confirm_kb(
            MenuCB(a="acc_del2", i=callback_data.i),
            MenuCB(a="acc", i=callback_data.i),
            yes_text="Удалить",
        ),
    )


@router.callback_query(MenuCB.filter(F.a == "acc_del2"))
async def cb_del2(query: CallbackQuery, callback_data: MenuCB) -> None:
    await ctx.store.delete_account(callback_data.i)
    accounts = await ctx.store.list_accounts()
    await safe_edit(query, accounts_html(accounts), accounts_kb(accounts))


@router.callback_query(MenuCB.filter(F.a == "acc_wh"))
async def cb_acc_wh(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.update_data(account_id=callback_data.i)
    await state.set_state(AccountSettings.work_hours)
    text = prompt_html(
        "Рабочие часы",
        "Формат: <code>09:00-21:00</code> или пусто для 24/7.\n"
        "Часовой пояс — из настроек бота.",
        "clock",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(AccountSettings.work_hours, F.text)
async def on_acc_wh(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    parsed = parse_work_hours(message.text or "")
    if parsed is None:
        await message.answer("Формат: 09:00-21:00 или пусто/24/7")
        return
    await state.clear()
    work_start, work_end = parsed
    acc = await ctx.store.update_account(
        int(data["account_id"]),
        work_start=work_start,
        work_end=work_end,
    )
    if not acc:
        await message.answer("Аккаунт не найден")
        return
    text, markup = await _payload(acc)
    await finish_input(message, text, markup)


@router.callback_query(MenuCB.filter(F.a == "acc_dly"))
async def cb_acc_dly(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.update_data(account_id=callback_data.i)
    await state.set_state(AccountSettings.delay)
    text = prompt_html(
        "Интервал аккаунта",
        "Пауза между сообщениями этого аккаунта, сек.\n"
        "Формат: <code>60-120</code> или <code>0</code> — глобальные настройки.",
        "clock",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(AccountSettings.delay, F.text)
async def on_acc_dly(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    raw = (message.text or "").replace("—", "-").strip()
    delay_min, delay_max = None, None
    if raw not in {"", "0", "-"}:
        parts = [p.strip() for p in raw.replace(",", "-").split("-") if p.strip()]
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            await message.answer("Нужны числа, например 60-120")
            return
        if not nums:
            await message.answer("Нужны числа, например 60-120")
            return
        delay_min = max(1, nums[0])
        delay_max = max(delay_min, nums[-1])
    await state.clear()
    acc = await ctx.store.update_account(
        int(data["account_id"]),
        delay_min=delay_min,
        delay_max=delay_max,
    )
    if not acc:
        await message.answer("Аккаунт не найден")
        return
    text, markup = await _payload(acc)
    await finish_input(message, text, markup)


@router.callback_query(MenuCB.filter(F.a == "acc_blk"))
async def cb_acc_blk(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.update_data(account_id=callback_data.i)
    await state.set_state(AccountSettings.blocklist)
    text = prompt_html(
        "Не отправлять",
        "Список контактов — по одному на строку.\n"
        "Они попадут в общий blocklist и не получат оффер.",
        "block",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(AccountSettings.blocklist, F.text)
async def on_acc_blk(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    parsed = parse_lines(message.text or "")
    added, skipped = await ctx.store.add_blocklist(
        [c for c in parsed.contacts if c.kind != "unknown"],
        note=f"acc #{data.get('account_id')}",
    )
    acc = await ctx.store.get_account(int(data["account_id"]))
    if not acc:
        await message.answer("Аккаунт не найден")
        return
    text, markup = await _payload(acc)
    await finish_input(
        message,
        prompt_html("Blocklist", f"Добавлено: <b>{added}</b> · дубли: {skipped}") + "\n\n" + text,
        markup,
    )
