from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_store, require_api_key
from app.api.serialize import to_dict
from app.store import Store

router = APIRouter(prefix="/history", tags=["history"], dependencies=[Depends(require_api_key)])


@router.get("/sends")
async def recent_sends(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    store: Store = Depends(get_store),
):
    items = await store.recent_sends(limit=limit, offset=offset)
    return {"ok": True, "items": to_dict(items)}


@router.get("/jobs")
async def recent_jobs(limit: int = Query(20, ge=1, le=200), store: Store = Depends(get_store)):
    items = await store.recent_jobs(limit=limit)
    return {"ok": True, "items": to_dict(items)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: int, store: Store = Depends(get_store)):
    job = await store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    logs = await store.job_logs(job_id, limit=100)
    return {"ok": True, "job": to_dict(job), "logs": to_dict(logs)}


@router.get("/jobs/{job_id}/logs")
async def job_logs(
    job_id: int,
    limit: int = Query(100, ge=1, le=1000),
    store: Store = Depends(get_store),
):
    if not await store.get_job(job_id):
        raise HTTPException(404, "Job not found")
    return {"ok": True, "logs": to_dict(await store.job_logs(job_id, limit=limit))}
