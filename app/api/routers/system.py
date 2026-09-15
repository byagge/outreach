from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_store, require_api_key
from app.api.serialize import to_dict
from app.config import get_settings
from app.jobs.runtime import runtime
from app.store import Store

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    return {
        "ok": True,
        "service": "outreach-api",
        "public_url": get_settings().api_public_url,
    }


@router.get("/stats", dependencies=[Depends(require_api_key)])
async def stats(store: Store = Depends(get_store)):
    counts = await store.counts()
    return {
        "ok": True,
        "counts": to_dict(counts),
        "outreach_running": runtime.is_running("outreach", 0),
        "running_jobs": runtime.running_keys(),
    }


@router.get("/info", dependencies=[Depends(require_api_key)])
async def info(store: Store = Depends(get_store)):
    settings = await store.outreach_settings()
    return {
        "ok": True,
        "version": "2.1.0",
        "timezone": get_settings().timezone,
        "settings": to_dict(settings),
        "outreach_running": runtime.is_running("outreach", 0),
    }
