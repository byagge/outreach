from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_store, require_api_key
from app.api.schemas import RawSetting, SettingsUpdate
from app.api.serialize import to_dict
from app.store import Store

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_api_key)])


@router.get("")
async def get_settings_api(store: Store = Depends(get_store)):
    return {"ok": True, "settings": to_dict(await store.outreach_settings())}


@router.patch("")
async def patch_settings(body: SettingsUpdate, store: Store = Depends(get_store)):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "Нет полей для обновления")
    settings = await store.update_settings(**data)
    return {"ok": True, "settings": to_dict(settings)}


@router.get("/raw/{key}")
async def get_raw_setting(key: str, store: Store = Depends(get_store)):
    return {"ok": True, "key": key, "value": await store.get_setting(key)}


@router.put("/raw/{key}")
async def put_raw_setting(key: str, body: RawSetting, store: Store = Depends(get_store)):
    await store.set_setting(key, body.value)
    return {"ok": True, "key": key, "value": body.value}
