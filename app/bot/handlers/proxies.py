from __future__ import annotations

from io import BytesIO

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import MenuCB, cancel_kb, confirm_kb, proxies_kb, proxy_kb
from app.bot.render import ask_input, finish_input, safe_edit
from app.bot.states import AddProxies
from app.context import ctx
from app.ui.screens import prompt_html, proxies_html, proxy_html
from app.tg.proxy_check import check_proxy
from app.utils.proxy import parse_proxy_blob, parse_proxy_file

router = Router()


@router.callback_query(MenuCB.filter(F.a == "proxies"))
async def cb_proxies(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    proxies = await ctx.store.list_proxies()
    await safe_edit(query, proxies_html(proxies), proxies_kb(proxies, callback_data.p))


@router.callback_query(MenuCB.filter(F.a == "px"))
async def cb_px(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    proxy = await ctx.store.get_proxy(callback_data.i)
    if not proxy:
        await query.answer("Нет прокси", show_alert=True)
        return
    accounts = await ctx.store.accounts_for_proxy(proxy.id)
    all_accounts = await ctx.store.list_accounts()
    bound_ids = {a.id for a in accounts}
    await safe_edit(query, proxy_html(proxy, accounts), proxy_kb(proxy, all_accounts, bound_ids))


@router.callback_query(MenuCB.filter(F.a == "px_chk"))
async def cb_px_chk(query: CallbackQuery, callback_data: MenuCB) -> None:
    proxy = await ctx.store.get_proxy(callback_data.i)
    if not proxy:
        await query.answer("Нет прокси", show_alert=True)
        return
    await query.answer("Проверяю…")
    ok, detail = await check_proxy(proxy)
    await ctx.store.mark_proxy(proxy.id, "ok" if ok else "error", detail)
    proxy = await ctx.store.get_proxy(proxy.id)
    accounts = await ctx.store.accounts_for_proxy(proxy.id)
    all_accounts = await ctx.store.list_accounts()
    bound_ids = {a.id for a in accounts}
    await safe_edit(query, proxy_html(proxy, accounts), proxy_kb(proxy, all_accounts, bound_ids))
    await query.message.answer(
        prompt_html("Проверка", f"{'OK' if ok else 'FAIL'}: {detail}", "shield")
    )


@router.callback_query(MenuCB.filter(F.a == "px_bind"))
async def cb_px_bind(query: CallbackQuery, callback_data: MenuCB) -> None:
    proxy_id = callback_data.i
    account_id = callback_data.p
    proxy = await ctx.store.get_proxy(proxy_id)
    acc = await ctx.store.get_account(account_id)
    if not proxy or not acc:
        await query.answer("Нет данных", show_alert=True)
        return
    bound = await ctx.store.proxies_for_account(account_id)
    is_bound = any(p.id == proxy_id for p in bound)
    await ctx.store.bind_proxy(account_id, proxy_id, not is_bound)
    await query.answer("Привязан" if not is_bound else "Отвязан")
    accounts = await ctx.store.accounts_for_proxy(proxy_id)
    all_accounts = await ctx.store.list_accounts()
    proxy = await ctx.store.get_proxy(proxy_id)
    bound_ids = {a.id for a in accounts}
    await safe_edit(query, proxy_html(proxy, accounts), proxy_kb(proxy, all_accounts, bound_ids))


@router.callback_query(MenuCB.filter(F.a == "px_add"))
async def cb_px_add(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddProxies.blob)
    text = prompt_html(
        "Прокси",
        "Пришлите список или файл <b>прямо сюда</b> — в CLI ничего писать не нужно.\n"
        "Тип определю сам: <b>socks5, socks4, http, https</b> (и mtproto, если это t.me/proxy).\n\n"
        "<code>host:port</code>\n"
        "<code>host:port:user:pass</code>\n"
        "<code>host:port:user:pass:http</code>\n"
        "<code>socks5://user:pass@host:port</code>\n"
        "<code>http://host:8080</code>\n"
        "<code>https://user:pass@host:443</code>\n"
        "<code>socks5 host port user pass</code>\n\n"
        "Файл: txt / csv / xlsx / json. Несколько прокси разложатся по аккаунтам.",
        "shield",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


async def _ingest_proxy_text(message: Message, items) -> None:
    if not items:
        await message.answer("Не нашёл ни одного прокси. Пришлите список или файл в этот чат.")
        return
    added, skipped = await ctx.store.add_proxies(items)
    proxies = await ctx.store.list_proxies()
    kinds: dict[str, int] = {}
    for item in items:
        kinds[item.scheme] = kinds.get(item.scheme, 0) + 1
    kind_s = ", ".join(f"{k} {v}" for k, v in sorted(kinds.items()))
    await finish_input(
        message,
        prompt_html(
            "Прокси",
            f"Определил типы: <b>{kind_s}</b>\n"
            f"Добавлено: <b>{added}</b>, дубликаты: {skipped}.\n"
            f"Всего в пуле: <b>{len(proxies)}</b>. Ротация пересобрана.",
            "shield",
        )
        + "\n\n"
        + proxies_html(proxies),
        proxies_kb(proxies),
    )


@router.message(AddProxies.blob, F.document)
async def on_px_file(message: Message, state: FSMContext) -> None:
    doc = message.document
    buf = BytesIO()
    await message.bot.download(doc, destination=buf)
    data = buf.getvalue()
    await state.clear()
    await _ingest_proxy_text(message, parse_proxy_file(data, doc.file_name or "proxies.txt"))


@router.message(AddProxies.blob, F.text)
async def on_px_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _ingest_proxy_text(message, parse_proxy_blob(message.text or ""))


@router.callback_query(MenuCB.filter(F.a == "px_rebal"))
async def cb_rebal(query: CallbackQuery) -> None:
    await ctx.store.rebalance_proxies()
    await query.answer("Раздал заново")
    proxies = await ctx.store.list_proxies()
    await safe_edit(query, proxies_html(proxies), proxies_kb(proxies))


@router.callback_query(MenuCB.filter(F.a == "px_del"))
async def cb_px_del(query: CallbackQuery, callback_data: MenuCB) -> None:
    await safe_edit(
        query,
        prompt_html("Удалить прокси", "Убрать из пула и с аккаунтов?", "warn"),
        confirm_kb(
            MenuCB(a="px_del2", i=callback_data.i),
            MenuCB(a="px", i=callback_data.i),
            yes_text="Удалить",
        ),
    )


@router.callback_query(MenuCB.filter(F.a == "px_del2"))
async def cb_px_del2(query: CallbackQuery, callback_data: MenuCB) -> None:
    await ctx.store.delete_proxy(callback_data.i)
    proxies = await ctx.store.list_proxies()
    await safe_edit(query, proxies_html(proxies), proxies_kb(proxies))
