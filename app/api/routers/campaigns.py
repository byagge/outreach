from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_store, require_api_key
from app.api.schemas import CampaignCreate, CampaignIdsBody, CampaignRename, TextCreate
from app.api.serialize import to_dict
from app.jobs.outreach import build_campaign_scope, run_outreach
from app.jobs.runtime import runtime
from app.store import Store

router = APIRouter(
    prefix="/campaigns", tags=["campaigns"], dependencies=[Depends(require_api_key)]
)


def _running_for(camp) -> bool:
    if camp.is_main:
        return runtime.is_running("outreach", 0)
    return runtime.is_running("campaign", camp.id)


async def _detail_payload(store: Store, campaign_id: int) -> dict:
    detail = await store.campaign_detail(campaign_id)
    if not detail:
        raise HTTPException(404, "Campaign not found")
    camp = detail["campaign"]
    detail["running"] = _running_for(camp)
    return {
        "ok": True,
        "campaign": to_dict(camp),
        "running": detail["running"],
        "pending": detail["pending"],
        "base_ids": detail["base_ids"],
        "account_ids": detail["account_ids"],
        "text_ids": detail["text_ids"],
        "bases": to_dict(detail["bases"]),
        "accounts": to_dict(detail["accounts"]),
        "texts": to_dict(detail["texts"]),
    }


@router.get("")
async def list_campaigns(store: Store = Depends(get_store)):
    camps = await store.list_campaigns()
    items = []
    for c in camps:
        row = to_dict(c)
        row["running"] = _running_for(c)
        if c.is_main:
            row["pending"] = await store.count_pending(mailing_only=True)
        else:
            base_ids = await store.campaign_base_ids(c.id)
            row["pending"] = await store.count_pending(
                base_ids=base_ids, mailing_only=False
            )
            row["bases_n"] = len(base_ids)
            row["accounts_n"] = len(await store.campaign_account_ids(c.id))
            row["texts_n"] = len(await store.campaign_text_ids(c.id))
        items.append(row)
    return {"ok": True, "items": items, "total": len(items)}


@router.post("")
async def create_campaign(body: CampaignCreate, store: Store = Depends(get_store)):
    camp = await store.add_campaign(body.name)
    return {"ok": True, "campaign": to_dict(camp)}


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: int, store: Store = Depends(get_store)):
    return await _detail_payload(store, campaign_id)


@router.patch("/{campaign_id}")
async def rename_campaign(
    campaign_id: int, body: CampaignRename, store: Store = Depends(get_store)
):
    camp = await store.get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")
    if camp.is_main:
        raise HTTPException(400, "Нельзя переименовать Основной")
    camp = await store.rename_campaign(campaign_id, body.name)
    return {"ok": True, "campaign": to_dict(camp)}


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: int, store: Store = Depends(get_store)):
    camp = await store.get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")
    if camp.is_main:
        raise HTTPException(400, "Нельзя удалить Основной")
    if runtime.is_running("campaign", campaign_id):
        raise HTTPException(409, "Сначала остановите кампанию")
    ok = await store.delete_campaign(campaign_id)
    if not ok:
        raise HTTPException(400, "Не удалось удалить")
    return {"ok": True}


@router.get("/{campaign_id}/status")
async def campaign_status(campaign_id: int, store: Store = Depends(get_store)):
    return await _detail_payload(store, campaign_id)


@router.put("/{campaign_id}/bases")
async def set_bases(
    campaign_id: int, body: CampaignIdsBody, store: Store = Depends(get_store)
):
    camp = await store.get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")
    if camp.is_main:
        raise HTTPException(400, "У Основного базы управляются через /v1/bases")
    ids = await store.set_campaign_bases(campaign_id, body.ids)
    return {"ok": True, "base_ids": ids}


@router.put("/{campaign_id}/accounts")
async def set_accounts(
    campaign_id: int, body: CampaignIdsBody, store: Store = Depends(get_store)
):
    camp = await store.get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")
    if camp.is_main:
        raise HTTPException(400, "У Основного аккаунты — assigned в /v1/accounts")
    ids = await store.set_campaign_accounts(campaign_id, body.ids)
    return {"ok": True, "account_ids": ids}


@router.put("/{campaign_id}/texts")
async def set_texts(
    campaign_id: int, body: CampaignIdsBody, store: Store = Depends(get_store)
):
    camp = await store.get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")
    if camp.is_main:
        raise HTTPException(400, "У Основного — все enabled офферы")
    ids = await store.set_campaign_texts(campaign_id, body.ids)
    return {"ok": True, "text_ids": ids}


@router.post("/{campaign_id}/texts")
async def create_campaign_text(
    campaign_id: int, body: TextCreate, store: Store = Depends(get_store)
):
    """Создать оффер только для этой кампании (не попадёт в основную рассылку)."""
    camp = await store.get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")
    if camp.is_main:
        raise HTTPException(400, "Для Основного создавайте офферы через POST /v1/texts")
    if not (body.text or "").strip() and not (body.photo_path or "").strip():
        raise HTTPException(400, "Нужен text или photo_path")
    item = await store.add_text(
        body.text,
        body.entities,
        photo_path=body.photo_path,
        title=body.title or "",
        campaign_id=campaign_id,
    )
    if body.enabled == 0:
        item = await store.update_text(item.id, enabled=0)
    return {"ok": True, "text": to_dict(item)}


@router.get("/{campaign_id}/texts")
async def list_campaign_texts(campaign_id: int, store: Store = Depends(get_store)):
    camp = await store.get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")
    owned = await store.list_texts(campaign_id=campaign_id, shared_only=False)
    linked_ids = await store.campaign_text_ids(campaign_id)
    shared_all = await store.list_texts(shared_only=True)
    shared_linked = [t for t in shared_all if t.id in set(linked_ids)]
    return {
        "ok": True,
        "owned": to_dict(owned),
        "shared_linked": to_dict(shared_linked),
        "text_ids": linked_ids,
    }


@router.post("/{campaign_id}/bases/{base_id}/toggle")
async def toggle_base(
    campaign_id: int, base_id: int, store: Store = Depends(get_store)
):
    camp = await store.get_campaign(campaign_id)
    if not camp or camp.is_main:
        raise HTTPException(400, "Недоступно для Основного / не найдено")
    if not await store.get_base(base_id):
        raise HTTPException(404, "Base not found")
    on = await store.toggle_campaign_base(campaign_id, base_id)
    return {
        "ok": True,
        "selected": on,
        "base_ids": await store.campaign_base_ids(campaign_id),
    }


@router.post("/{campaign_id}/accounts/{account_id}/toggle")
async def toggle_account(
    campaign_id: int, account_id: int, store: Store = Depends(get_store)
):
    camp = await store.get_campaign(campaign_id)
    if not camp or camp.is_main:
        raise HTTPException(400, "Недоступно для Основного / не найдено")
    if not await store.get_account(account_id):
        raise HTTPException(404, "Account not found")
    on = await store.toggle_campaign_account(campaign_id, account_id)
    return {
        "ok": True,
        "selected": on,
        "account_ids": await store.campaign_account_ids(campaign_id),
    }


@router.post("/{campaign_id}/texts/{text_id}/toggle")
async def toggle_text(
    campaign_id: int, text_id: int, store: Store = Depends(get_store)
):
    camp = await store.get_campaign(campaign_id)
    if not camp or camp.is_main:
        raise HTTPException(400, "Недоступно для Основного / не найдено")
    if not await store.get_text(text_id):
        raise HTTPException(404, "Text not found")
    on = await store.toggle_campaign_text(campaign_id, text_id)
    return {
        "ok": True,
        "selected": on,
        "text_ids": await store.campaign_text_ids(campaign_id),
    }


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: int, store: Store = Depends(get_store)):
    camp = await store.get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")
    if camp.is_main:
        raise HTTPException(400, "Для Основного используйте POST /v1/run/start")

    try:
        scope = await build_campaign_scope(store, campaign_id)
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e

    if not scope.base_ids:
        raise HTTPException(400, "Выберите хотя бы одну базу")
    if not scope.account_ids:
        raise HTTPException(400, "Выберите хотя бы один аккаунт")
    if not scope.text_ids:
        raise HTTPException(400, "Выберите хотя бы один оффер")

    accounts = [
        a
        for a in await store.list_accounts()
        if a.id in set(scope.account_ids) and a.has_telethon
    ]
    if not accounts:
        raise HTTPException(400, "Нет аккаунтов с session")

    pending = await store.count_pending(base_ids=scope.base_ids, mailing_only=False)
    settings = await store.outreach_settings()
    if pending <= 0 and not settings.continuous:
        raise HTTPException(400, "В выбранных базах нет pending")

    if runtime.is_running("campaign", campaign_id):
        raise HTTPException(409, "Уже запущено")

    try:
        runtime.spawn("campaign", campaign_id, run_outreach(store, None, None, scope))
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e

    return {
        "ok": True,
        "running": True,
        "pending": pending,
        "campaign": to_dict(camp),
    }


@router.post("/{campaign_id}/stop")
async def stop_campaign(campaign_id: int, store: Store = Depends(get_store)):
    camp = await store.get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")
    if camp.is_main:
        raise HTTPException(400, "Для Основного используйте POST /v1/run/stop")
    if not runtime.is_running("campaign", campaign_id):
        return {"ok": True, "running": False, "detail": "already stopped"}
    runtime.request_cancel("campaign", campaign_id)
    return {"ok": True, "running": False, "detail": "stop requested"}
