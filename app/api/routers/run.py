from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_store, require_api_key
from app.api.serialize import to_dict
from app.jobs.outreach import run_outreach
from app.jobs.runtime import runtime
from app.store import Store

router = APIRouter(prefix="/run", tags=["run"], dependencies=[Depends(require_api_key)])


@router.get("/status")
async def run_status(store: Store = Depends(get_store)):
    counts = await store.counts()
    settings = await store.outreach_settings()
    return {
        "ok": True,
        "running": runtime.is_running("outreach", 0),
        "counts": to_dict(counts),
        "continuous": settings.continuous,
        "running_keys": runtime.running_keys(),
    }


@router.post("/start")
async def run_start(store: Store = Depends(get_store)):
    counts = await store.counts()
    settings = await store.outreach_settings()
    accounts = [a for a in await store.list_accounts() if a.assigned and a.has_telethon]
    if not accounts:
        raise HTTPException(400, "Нет назначенных аккаунтов с session")
    if counts.pending <= 0 and not settings.continuous:
        raise HTTPException(400, "База пустая")
    if counts.texts <= 0:
        raise HTTPException(400, "Нет офферов")
    if runtime.is_running("outreach", 0):
        raise HTTPException(409, "Уже запущено")
    try:
        runtime.spawn("outreach", 0, run_outreach(store, None, None))
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "running": True, "pending": counts.pending}


@router.post("/stop")
async def run_stop():
    if not runtime.is_running("outreach", 0):
        return {"ok": True, "running": False, "detail": "already stopped"}
    runtime.request_cancel("outreach", 0)
    return {"ok": True, "running": False, "detail": "stop requested"}
