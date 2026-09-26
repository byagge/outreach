from __future__ import annotations

import json
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import (
    MenuCB,
    campaign_kb,
    campaign_pick_accounts_kb,
    campaign_pick_bases_kb,
    campaign_pick_texts_kb,
    campaign_text_kb,
    campaigns_kb,
    cancel_kb,
    confirm_kb,
)
from app.bot.render import ask_input, finish_input, safe_edit
from app.bot.states import AddCampaign, CampaignText, RenameCampaign
from app.config import TEXTS_DIR
from app.context import ctx
from app.jobs.outreach import build_campaign_scope, run_outreach
from app.jobs.runtime import runtime
from app.ui.screens import campaign_html, campaigns_html, prompt_html, text_html
from app.utils.entities import from_aiogram_message

router = Router()


async def _save_camp_photo(message: Message, prefix: str) -> str:
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


def _page_of(items: list, item_id: int, *, attr: str = "id", per: int = 8) -> int:
    for i, obj in enumerate(items):
        if getattr(obj, attr) == item_id:
            return i // per
    return 0


async def _camps_screen(page: int = 0):
    camps = await ctx.store.list_campaigns()
    return campaigns_html(camps), campaigns_kb(camps, page)


async def _camp_screen(campaign_id: int):
    camp = await ctx.store.get_campaign(campaign_id)
    if not camp:
        return None, None
    if camp.is_main:
        running = runtime.is_running("outreach", 0)
        pending = await ctx.store.count_pending(mailing_only=True)
        text = campaign_html(camp, running=running, pending=pending)
        return text, campaign_kb(camp, running)

    running = runtime.is_running("campaign", camp.id)
    detail = await ctx.store.campaign_detail(camp.id)
    assert detail is not None
    text = campaign_html(
        camp,
        running=running,
        bases_n=len(detail["base_ids"]),
        accounts_n=len(detail["account_ids"]),
        texts_n=len(detail["text_ids"]),
        pending=detail["pending"],
        base_names=[b.name for b in detail["bases"]],
        account_names=[a.label for a in detail["accounts"]],
        text_names=[(t.title or f"#{t.id}") for t in detail["texts"]],
    )
    return text, campaign_kb(camp, running)


@router.callback_query(MenuCB.filter(F.a == "camps"))
async def cb_camps(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _camps_screen(page=max(0, callback_data.p))
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "camp"))
async def cb_camp(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _camp_screen(callback_data.i)
    if not text:
        await query.answer("Нет кампании", show_alert=True)
        return
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "camp_add"))
async def cb_camp_add(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddCampaign.name)
    text = prompt_html(
        "Новая кампания",
        "Пришлите название. Потом выберите базы, аккаунты и офферы "
        "(кнопки «Все» / «Снять» ускоряют выбор).",
        "folder",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(AddCampaign.name, F.text)
async def on_camp_add(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()[:60]
    await state.clear()
    if not name:
        await message.answer("Пустое имя")
        return
    camp = await ctx.store.add_campaign(name)
    text, markup = await _camp_screen(camp.id)
    await finish_input(
        message,
        prompt_html("Кампания", f"Создана <b>{escape(camp.name)}</b>", "check")
        + "\n\n"
        + (text or ""),
        markup,
    )


@router.callback_query(MenuCB.filter(F.a == "camp_ren"))
async def cb_camp_ren(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    camp = await ctx.store.get_campaign(callback_data.i)
    if not camp or camp.is_main:
        await query.answer("Нельзя переименовать Основной", show_alert=True)
        return
    await state.set_state(RenameCampaign.name)
    await state.update_data(campaign_id=camp.id)
    text = prompt_html("Переименовать", f"Сейчас: <b>{escape(camp.name)}</b>\nНовое имя:", "hammer")
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(RenameCampaign.name, F.text)
async def on_camp_ren(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    name = (message.text or "").strip()[:60]
    camp_id = int(data.get("campaign_id") or 0)
    if not name or not camp_id:
        await message.answer("Отмена")
        return
    camp = await ctx.store.rename_campaign(camp_id, name)
    text, markup = await _camp_screen(camp_id)
    await finish_input(
        message,
        prompt_html("Кампания", f"Имя: <b>{escape(camp.name if camp else name)}</b>", "check")
        + "\n\n"
        + (text or ""),
        markup,
    )


@router.callback_query(MenuCB.filter(F.a == "camp_del"))
async def cb_camp_del(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp = await ctx.store.get_campaign(callback_data.i)
    if not camp or camp.is_main:
        await query.answer("Нельзя удалить Основной", show_alert=True)
        return
    if runtime.is_running("campaign", camp.id):
        await query.answer("Сначала остановите кампанию", show_alert=True)
        return
    await safe_edit(
        query,
        prompt_html(
            "Удалить",
            f"Удалить кампанию <b>{escape(camp.name)}</b>?\nБазы и офферы не трогаются.",
            "warn",
        ),
        confirm_kb(
            MenuCB(a="camp_del2", i=camp.id),
            MenuCB(a="camp", i=camp.id),
            yes_text="Удалить",
        ),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_del2"))
async def cb_camp_del2(query: CallbackQuery, callback_data: MenuCB) -> None:
    ok = await ctx.store.delete_campaign(callback_data.i)
    await query.answer("Удалено" if ok else "Не удалось")
    text, markup = await _camps_screen()
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "camp_bases"))
async def cb_camp_bases(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp = await ctx.store.get_campaign(callback_data.i)
    if not camp or camp.is_main:
        await query.answer("У Основного базы включаются в разделе Базы", show_alert=True)
        return
    bases = await ctx.store.list_bases()
    selected = set(await ctx.store.campaign_base_ids(camp.id))
    page = max(0, callback_data.p)
    body = (
        f"Кампания <b>{escape(camp.name)}</b>\n"
        f"⊕ = отдельная база. Выбрано: <b>{len(selected)}</b> / {len(bases)}"
    )
    await safe_edit(
        query,
        prompt_html("Базы кампании", body, "users"),
        campaign_pick_bases_kb(bases, selected, camp.id, page),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_tb"))
async def cb_camp_tb(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp_id = callback_data.i
    base_id = callback_data.p
    on = await ctx.store.toggle_campaign_base(camp_id, base_id)
    await query.answer("Вкл" if on else "Выкл")
    bases = await ctx.store.list_bases()
    selected = set(await ctx.store.campaign_base_ids(camp_id))
    camp = await ctx.store.get_campaign(camp_id)
    page = _page_of(bases, base_id)
    body = (
        f"Кампания <b>{escape(camp.name if camp else '')}</b>\n"
        f"Выбрано: <b>{len(selected)}</b> / {len(bases)}"
    )
    await safe_edit(
        query,
        prompt_html("Базы кампании", body, "users"),
        campaign_pick_bases_kb(bases, selected, camp_id, page),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_ball"))
async def cb_camp_ball(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp_id = callback_data.i
    bases = await ctx.store.list_bases()
    await ctx.store.set_campaign_bases(camp_id, [b.id for b in bases])
    await query.answer(f"Все {len(bases)}")
    camp = await ctx.store.get_campaign(camp_id)
    selected = set(await ctx.store.campaign_base_ids(camp_id))
    body = (
        f"Кампания <b>{escape(camp.name if camp else '')}</b>\n"
        f"Выбрано: <b>{len(selected)}</b> / {len(bases)}"
    )
    await safe_edit(
        query,
        prompt_html("Базы кампании", body, "users"),
        campaign_pick_bases_kb(bases, selected, camp_id, 0),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_bclr"))
async def cb_camp_bclr(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp_id = callback_data.i
    await ctx.store.set_campaign_bases(camp_id, [])
    await query.answer("Снято")
    bases = await ctx.store.list_bases()
    camp = await ctx.store.get_campaign(camp_id)
    body = (
        f"Кампания <b>{escape(camp.name if camp else '')}</b>\n"
        f"Выбрано: <b>0</b> / {len(bases)}"
    )
    await safe_edit(
        query,
        prompt_html("Базы кампании", body, "users"),
        campaign_pick_bases_kb(bases, set(), camp_id, 0),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_accs"))
async def cb_camp_accs(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp = await ctx.store.get_campaign(callback_data.i)
    if not camp or camp.is_main:
        await query.answer("У Основного — назначение в Аккаунтах / Рассылке", show_alert=True)
        return
    accounts = await ctx.store.list_accounts()
    live = [a for a in accounts if a.has_telethon]
    selected = set(await ctx.store.campaign_account_ids(camp.id))
    page = max(0, callback_data.p)
    body = (
        f"Кампания <b>{escape(camp.name)}</b>\n"
        f"Аккаунты с session. Выбрано: <b>{len(selected)}</b> / {len(live)}"
    )
    await safe_edit(
        query,
        prompt_html("Аккаунты кампании", body, "user"),
        campaign_pick_accounts_kb(accounts, selected, camp.id, page),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_ta"))
async def cb_camp_ta(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp_id = callback_data.i
    account_id = callback_data.p
    on = await ctx.store.toggle_campaign_account(camp_id, account_id)
    await query.answer("Вкл" if on else "Выкл")
    accounts = await ctx.store.list_accounts()
    live = [a for a in accounts if a.has_telethon]
    selected = set(await ctx.store.campaign_account_ids(camp_id))
    camp = await ctx.store.get_campaign(camp_id)
    page = _page_of(live, account_id)
    body = (
        f"Кампания <b>{escape(camp.name if camp else '')}</b>\n"
        f"Выбрано: <b>{len(selected)}</b> / {len(live)}"
    )
    await safe_edit(
        query,
        prompt_html("Аккаунты кампании", body, "user"),
        campaign_pick_accounts_kb(accounts, selected, camp_id, page),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_aall"))
async def cb_camp_aall(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp_id = callback_data.i
    accounts = await ctx.store.list_accounts()
    live = [a for a in accounts if a.has_telethon]
    await ctx.store.set_campaign_accounts(camp_id, [a.id for a in live])
    await query.answer(f"Все {len(live)}")
    selected = set(await ctx.store.campaign_account_ids(camp_id))
    camp = await ctx.store.get_campaign(camp_id)
    body = (
        f"Кампания <b>{escape(camp.name if camp else '')}</b>\n"
        f"Выбрано: <b>{len(selected)}</b> / {len(live)}"
    )
    await safe_edit(
        query,
        prompt_html("Аккаунты кампании", body, "user"),
        campaign_pick_accounts_kb(accounts, selected, camp_id, 0),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_aclr"))
async def cb_camp_aclr(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp_id = callback_data.i
    await ctx.store.set_campaign_accounts(camp_id, [])
    await query.answer("Снято")
    accounts = await ctx.store.list_accounts()
    live = [a for a in accounts if a.has_telethon]
    camp = await ctx.store.get_campaign(camp_id)
    body = (
        f"Кампания <b>{escape(camp.name if camp else '')}</b>\n"
        f"Выбрано: <b>0</b> / {len(live)}"
    )
    await safe_edit(
        query,
        prompt_html("Аккаунты кампании", body, "user"),
        campaign_pick_accounts_kb(accounts, set(), camp_id, 0),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_txs"))
async def cb_camp_txs(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    camp = await ctx.store.get_campaign(callback_data.i)
    if not camp or camp.is_main:
        await query.answer("У Основного — раздел «Офферы» в меню", show_alert=True)
        return
    owned = await ctx.store.list_texts(campaign_id=camp.id, shared_only=False)
    shared = await ctx.store.list_texts(shared_only=True)
    selected = set(await ctx.store.campaign_text_ids(camp.id))
    shared_on = {t.id for t in shared if t.id in selected}
    page = max(0, callback_data.p)
    body = (
        f"Кампания <b>{escape(camp.name)}</b>\n\n"
        f"⊕ <b>Свои офферы</b> — только для этой кампании, "
        f"в основную рассылку <b>не попадают</b>.\n"
        f"Своих: <b>{len(owned)}</b> · из общих прикреплено: <b>{len(shared_on)}</b>"
    )
    await safe_edit(
        query,
        prompt_html("Офферы кампании", body, "mega"),
        campaign_pick_texts_kb(owned, shared, shared_on, camp.id, page, mode="owned"),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_tshare"))
async def cb_camp_tshare(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp = await ctx.store.get_campaign(callback_data.i)
    if not camp or camp.is_main:
        await query.answer("Нет", show_alert=True)
        return
    owned = await ctx.store.list_texts(campaign_id=camp.id, shared_only=False)
    shared = await ctx.store.list_texts(shared_only=True)
    selected = set(await ctx.store.campaign_text_ids(camp.id))
    shared_on = {t.id for t in shared if t.id in selected}
    page = max(0, callback_data.p)
    body = (
        f"Кампания <b>{escape(camp.name)}</b>\n"
        f"Прикрепить общие офферы (из раздела «Офферы»). "
        f"Выбрано: <b>{len(shared_on)}</b> / {len(shared)}"
    )
    await safe_edit(
        query,
        prompt_html("Общие офферы", body, "stack"),
        campaign_pick_texts_kb(owned, shared, shared_on, camp.id, page, mode="share"),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_tt"))
async def cb_camp_tt(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp_id = callback_data.i
    text_id = callback_data.p
    item = await ctx.store.get_text(text_id)
    if item and item.campaign_id:
        await query.answer("Это оффер кампании — откройте его в списке", show_alert=True)
        return
    on = await ctx.store.toggle_campaign_text(camp_id, text_id)
    await query.answer("Вкл" if on else "Выкл")
    owned = await ctx.store.list_texts(campaign_id=camp_id, shared_only=False)
    shared = await ctx.store.list_texts(shared_only=True)
    selected = set(await ctx.store.campaign_text_ids(camp_id))
    shared_on = {t.id for t in shared if t.id in selected}
    camp = await ctx.store.get_campaign(camp_id)
    page = _page_of(shared, text_id)
    body = (
        f"Кампания <b>{escape(camp.name if camp else '')}</b>\n"
        f"Выбрано общих: <b>{len(shared_on)}</b> / {len(shared)}"
    )
    await safe_edit(
        query,
        prompt_html("Общие офферы", body, "stack"),
        campaign_pick_texts_kb(owned, shared, shared_on, camp_id, page, mode="share"),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_tall"))
async def cb_camp_tall(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp_id = callback_data.i
    owned = await ctx.store.list_texts(campaign_id=camp_id, shared_only=False)
    shared = await ctx.store.list_texts(shared_only=True)
    ids = [t.id for t in owned] + [t.id for t in shared]
    await ctx.store.set_campaign_texts(camp_id, ids)
    await query.answer(f"Все общие + свои ({len(ids)})")
    shared_on = {t.id for t in shared}
    camp = await ctx.store.get_campaign(camp_id)
    body = (
        f"Кампания <b>{escape(camp.name if camp else '')}</b>\n"
        f"Выбрано общих: <b>{len(shared_on)}</b> / {len(shared)}"
    )
    await safe_edit(
        query,
        prompt_html("Общие офферы", body, "stack"),
        campaign_pick_texts_kb(owned, shared, shared_on, camp_id, 0, mode="share"),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_tclr"))
async def cb_camp_tclr(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp_id = callback_data.i
    owned = await ctx.store.list_texts(campaign_id=camp_id, shared_only=False)
    # снять только общие, свои оставить привязанными
    await ctx.store.set_campaign_texts(camp_id, [t.id for t in owned])
    await query.answer("Общие сняты")
    shared = await ctx.store.list_texts(shared_only=True)
    camp = await ctx.store.get_campaign(camp_id)
    body = (
        f"Кампания <b>{escape(camp.name if camp else '')}</b>\n"
        f"Выбрано общих: <b>0</b> / {len(shared)}"
    )
    await safe_edit(
        query,
        prompt_html("Общие офферы", body, "stack"),
        campaign_pick_texts_kb(owned, shared, set(), camp_id, 0, mode="share"),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_tx_add"))
async def cb_camp_tx_add(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    camp = await ctx.store.get_campaign(callback_data.i)
    if not camp or camp.is_main:
        await query.answer("Нет", show_alert=True)
        return
    await state.set_state(CampaignText.add)
    await state.update_data(campaign_id=camp.id)
    text = prompt_html(
        "Оффер кампании",
        f"Кампания <b>{escape(camp.name)}</b>\n\n"
        "Пришлите сообщение — текст, premium emoji, оформление, фото.\n"
        "Оффер будет <b>только</b> у этой кампании (не в основной «Офферы»).",
        "inbox",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(CampaignText.add, F.text | F.photo | F.caption | F.document)
async def on_camp_tx_add(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    camp_id = int(data.get("campaign_id") or 0)
    await state.clear()
    if not camp_id:
        await message.answer("Ошибка: нет кампании")
        return
    text, entities = from_aiogram_message(message)
    photo_path = await _save_camp_photo(message, f"camp{camp_id}")
    if not (text or "").strip() and not photo_path:
        await message.answer("Нужен текст или фото")
        return
    n = len(await ctx.store.list_texts(campaign_id=camp_id, shared_only=False)) + 1
    item = await ctx.store.add_text(
        text,
        entities,
        photo_path,
        title=f"камп. #{n}",
        campaign_id=camp_id,
    )
    owned = await ctx.store.list_texts(campaign_id=camp_id, shared_only=False)
    shared = await ctx.store.list_texts(shared_only=True)
    selected = set(await ctx.store.campaign_text_ids(camp_id))
    shared_on = {t.id for t in shared if t.id in selected}
    camp = await ctx.store.get_campaign(camp_id)
    body = (
        f"Сохранён <b>{escape(item.title)}</b> — только для кампании.\n"
        f"Своих: <b>{len(owned)}</b>"
    )
    await finish_input(
        message,
        prompt_html("Оффер кампании", body, "check")
        + "\n\n"
        + text_html(item),
        campaign_pick_texts_kb(
            owned, shared, shared_on, camp_id, max(0, (len(owned) - 1) // 8), mode="owned"
        )
        if camp
        else campaign_text_kb(item, camp_id),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_tx"))
async def cb_camp_tx(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    await state.clear()
    item = await ctx.store.get_text(callback_data.i)
    camp_id = callback_data.p
    if not item or item.campaign_id != camp_id:
        await query.answer("Нет оффера кампании", show_alert=True)
        return
    await safe_edit(query, text_html(item), campaign_text_kb(item, camp_id))


@router.callback_query(MenuCB.filter(F.a == "camp_tx_on"))
async def cb_camp_tx_on(query: CallbackQuery, callback_data: MenuCB) -> None:
    item = await ctx.store.get_text(callback_data.i)
    camp_id = callback_data.p
    if not item or item.campaign_id != camp_id:
        await query.answer("Нет", show_alert=True)
        return
    item = await ctx.store.update_text(item.id, enabled=0 if item.enabled else 1)
    await query.answer("Ок")
    if item:
        await safe_edit(query, text_html(item), campaign_text_kb(item, camp_id))


@router.callback_query(MenuCB.filter(F.a == "camp_tx_edit"))
async def cb_camp_tx_edit(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    item = await ctx.store.get_text(callback_data.i)
    camp_id = callback_data.p
    if not item or item.campaign_id != camp_id:
        await query.answer("Нет", show_alert=True)
        return
    await state.set_state(CampaignText.edit)
    await state.update_data(text_id=item.id, campaign_id=camp_id)
    text = prompt_html(
        "Изменить оффер",
        f"Сейчас: <b>{escape(item.title or f'#{item.id}')}</b>\n"
        "Пришлите новое сообщение (текст / emoji / фото).",
        "hammer",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(CampaignText.edit, F.text | F.photo | F.caption | F.document)
async def on_camp_tx_edit(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    text_id = int(data.get("text_id") or 0)
    camp_id = int(data.get("campaign_id") or 0)
    item = await ctx.store.get_text(text_id)
    if not item or item.campaign_id != camp_id:
        await message.answer("Не найден")
        return
    text, entities = from_aiogram_message(message)
    photo_path = await _save_camp_photo(message, f"camp{camp_id}_{text_id}")
    fields: dict = {
        "text": text,
        "entities_json": json.dumps(entities, ensure_ascii=False),
    }
    if photo_path:
        fields["photo_path"] = photo_path
    if not (text or "").strip() and not photo_path and not item.photo_path:
        await message.answer("Пустое сообщение")
        return
    updated = await ctx.store.update_text(text_id, **fields)
    await finish_input(
        message,
        prompt_html("Обновлено", "Оффер кампании сохранён", "check")
        + "\n\n"
        + text_html(updated or item),
        campaign_text_kb(updated or item, camp_id),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_tx_ren"))
async def cb_camp_tx_ren(query: CallbackQuery, callback_data: MenuCB, state: FSMContext) -> None:
    item = await ctx.store.get_text(callback_data.i)
    camp_id = callback_data.p
    if not item or item.campaign_id != camp_id:
        await query.answer("Нет", show_alert=True)
        return
    await state.set_state(CampaignText.title)
    await state.update_data(text_id=item.id, campaign_id=camp_id)
    text = prompt_html(
        "Название",
        f"Сейчас: <b>{escape(item.title or f'#{item.id}')}</b>\nНовое имя:",
        "bookmark",
    )
    await safe_edit(query, text, cancel_kb())
    await ask_input(query, text)


@router.message(CampaignText.title, F.text)
async def on_camp_tx_ren(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    title = (message.text or "").strip()[:80]
    text_id = int(data.get("text_id") or 0)
    camp_id = int(data.get("campaign_id") or 0)
    if not title:
        await message.answer("Пусто")
        return
    item = await ctx.store.update_text(text_id, title=title)
    if not item or item.campaign_id != camp_id:
        await message.answer("Не найден")
        return
    await finish_input(
        message,
        prompt_html("Название", f"Сохранено: <b>{escape(title)}</b>", "check")
        + "\n\n"
        + text_html(item),
        campaign_text_kb(item, camp_id),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_tx_nophoto"))
async def cb_camp_tx_nophoto(query: CallbackQuery, callback_data: MenuCB) -> None:
    item = await ctx.store.get_text(callback_data.i)
    camp_id = callback_data.p
    if not item or item.campaign_id != camp_id:
        await query.answer("Нет", show_alert=True)
        return
    if not (item.text or "").strip():
        await query.answer("Нельзя: нет текста", show_alert=True)
        return
    item = await ctx.store.update_text(item.id, photo_path="")
    await query.answer("Фото убрано")
    if item:
        await safe_edit(query, text_html(item), campaign_text_kb(item, camp_id))


@router.callback_query(MenuCB.filter(F.a == "camp_tx_del"))
async def cb_camp_tx_del(query: CallbackQuery, callback_data: MenuCB) -> None:
    await safe_edit(
        query,
        prompt_html("Удалить", "Удалить оффер кампании безвозвратно?", "warn"),
        confirm_kb(
            MenuCB(a="camp_tx_del2", i=callback_data.i, p=callback_data.p),
            MenuCB(a="camp_tx", i=callback_data.i, p=callback_data.p),
            yes_text="Удалить",
        ),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_tx_del2"))
async def cb_camp_tx_del2(query: CallbackQuery, callback_data: MenuCB) -> None:
    item = await ctx.store.get_text(callback_data.i)
    camp_id = callback_data.p
    if not item or item.campaign_id != camp_id:
        await query.answer("Уже нет")
    else:
        await ctx.store.delete_text(item.id)
        await query.answer("Удалено")
    owned = await ctx.store.list_texts(campaign_id=camp_id, shared_only=False)
    shared = await ctx.store.list_texts(shared_only=True)
    selected = set(await ctx.store.campaign_text_ids(camp_id))
    shared_on = {t.id for t in shared if t.id in selected}
    camp = await ctx.store.get_campaign(camp_id)
    body = (
        f"Кампания <b>{escape(camp.name if camp else '')}</b>\n"
        f"Своих: <b>{len(owned)}</b> · из общих: <b>{len(shared_on)}</b>"
    )
    await safe_edit(
        query,
        prompt_html("Офферы кампании", body, "mega"),
        campaign_pick_texts_kb(owned, shared, shared_on, camp_id, 0, mode="owned"),
    )


@router.callback_query(MenuCB.filter(F.a == "camp_go"))
async def cb_camp_go(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp = await ctx.store.get_campaign(callback_data.i)
    if not camp or camp.is_main:
        await query.answer("Для Основного используйте Старт", show_alert=True)
        return
    if runtime.is_running("campaign", camp.id):
        await query.answer("Уже запущено", show_alert=True)
        return

    try:
        scope = await build_campaign_scope(ctx.store, camp.id)
    except RuntimeError as e:
        await query.answer(str(e), show_alert=True)
        return

    if not scope.base_ids:
        await query.answer("Выберите хотя бы одну базу", show_alert=True)
        return
    if not scope.account_ids:
        await query.answer("Выберите хотя бы один аккаунт", show_alert=True)
        return
    if not scope.text_ids:
        await query.answer("Добавьте/выберите хотя бы один оффер", show_alert=True)
        return

    accounts = [
        a
        for a in await ctx.store.list_accounts()
        if a.id in set(scope.account_ids) and a.has_telethon
    ]
    if not accounts:
        await query.answer("Нет аккаунтов с session", show_alert=True)
        return

    pending = await ctx.store.count_pending(base_ids=scope.base_ids, mailing_only=False)
    settings = await ctx.store.outreach_settings()
    if pending <= 0 and not settings.continuous:
        await query.answer("В выбранных базах нет pending", show_alert=True)
        return

    chat_id = query.from_user.id if query.from_user else None
    try:
        runtime.spawn(
            "campaign",
            camp.id,
            run_outreach(ctx.store, query.bot, chat_id, scope),
        )
    except RuntimeError as e:
        await query.answer(str(e), show_alert=True)
        return

    await query.answer("Запускаю кампанию")
    text, markup = await _camp_screen(camp.id)
    await safe_edit(query, text, markup)


@router.callback_query(MenuCB.filter(F.a == "camp_stop"))
async def cb_camp_stop(query: CallbackQuery, callback_data: MenuCB) -> None:
    camp = await ctx.store.get_campaign(callback_data.i)
    if not camp or camp.is_main:
        await query.answer("Для Основного — Стоп в меню", show_alert=True)
        return
    if not runtime.is_running("campaign", camp.id):
        await query.answer("Уже не запущено")
    else:
        runtime.request_cancel("campaign", camp.id)
        await query.answer("Останавливаю…")
    text, markup = await _camp_screen(camp.id)
    await safe_edit(query, text, markup)
