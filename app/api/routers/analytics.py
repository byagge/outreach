from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.analytics import build_report, period_bounds
from app.api.deps import get_store, require_api_key
from app.api.serialize import to_dict
from app.jobs.replies import AnswerError, send_answer
from app.store import Store
from app.utils.report import build_report_xlsx

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(require_api_key)])
replies_router = APIRouter(prefix="/replies", tags=["replies"], dependencies=[Depends(require_api_key)])

DIMENSIONS = ("account", "text", "campaign", "base", "kind", "proxy", "hour", "weekday")


class AnswerBody(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    entities: list[dict[str, Any]] | None = None


class StatusBody(BaseModel):
    status: str = Field(pattern="^(new|ignored)$")


def _filters(
    days: int | None = Query(None, ge=1, le=3650, description="Последние N дней (1 = 24 ч). Пусто — всё время"),
    since: str | None = Query(None, description="ISO UTC, начало периода (если не задан days)"),
    until: str | None = Query(None, description="ISO UTC, конец периода"),
    campaign_id: int | None = None,
    account_id: int | None = None,
) -> dict[str, Any]:
    return {
        "days": days,
        "since": since,
        "until": until,
        "campaign_id": campaign_id,
        "account_id": account_id,
    }


@router.get("/report")
async def full_report(f: dict = Depends(_filters), store: Store = Depends(get_store)):
    """Полный отчёт: обзор, воронка, скорость ответов, срезы, динамика, ошибки, выводы."""
    return {"ok": True, **await build_report(store, **f)}


@router.get("/overview")
async def overview(f: dict = Depends(_filters), store: Store = Depends(get_store)):
    r = await build_report(store, **f)
    return {
        "ok": True,
        "period": r["period"],
        "overview": r["overview"],
        "funnel": r["funnel"],
        "latency": r["latency"],
        "our_response": r["our_response"],
        "backlog": r["backlog"],
        "insights": r["insights"],
    }


@router.get("/breakdown/{dim}")
async def breakdown(dim: str, f: dict = Depends(_filters), store: Store = Depends(get_store)):
    """Срез: account | text | campaign | base | kind | proxy | hour | weekday."""
    if dim not in DIMENSIONS:
        raise HTTPException(404, f"Неизвестный срез. Доступно: {', '.join(DIMENSIONS)}")
    r = await build_report(store, **f)
    return {"ok": True, "dim": dim, "period": r["period"], "items": r["dims"][dim]}


@router.get("/timeline")
async def timeline(f: dict = Depends(_filters), store: Store = Depends(get_store)):
    r = await build_report(store, **f)
    return {"ok": True, "daily": r["daily"], "reply_hours": r["reply_hours"]}


@router.get("/errors")
async def errors(f: dict = Depends(_filters), store: Store = Depends(get_store)):
    r = await build_report(store, **f)
    return {"ok": True, "items": r["errors"]}


@router.get("/report.xlsx")
async def report_xlsx(f: dict = Depends(_filters), store: Store = Depends(get_store)):
    data, _ = await build_report_xlsx(store, **f)
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="outreach_report.xlsx"'},
    )


# ------------------------------------------------------------------ replies


@replies_router.get("")
async def list_replies(
    status: str | None = Query(None, pattern="^(new|answered|ignored|redirect)$"),
    redirects: bool = Query(False, description="true — только сообщения со ссылками (редиректы)"),
    account_id: int | None = None,
    campaign_id: int | None = None,
    text_id: int | None = None,
    days: int | None = Query(None, ge=1, le=3650),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    store: Store = Depends(get_store),
):
    """Ответы (без ссылок). redirects=true — отдельно сообщения со ссылками."""
    since, _ = period_bounds(days)
    kw = dict(
        status=status,
        valid=not redirects,
        account_id=account_id,
        campaign_id=campaign_id,
        text_id=text_id,
        since=since,
    )
    items = await store.list_replies(limit=limit, offset=offset, **kw)
    total = await store.count_replies(**kw)
    return {"ok": True, "items": to_dict(items), "total": total}


@replies_router.get("/{reply_id}")
async def get_reply(reply_id: int, store: Store = Depends(get_store)):
    reply = await store.get_reply(reply_id)
    if not reply:
        raise HTTPException(404, "Reply not found")
    return {
        "ok": True,
        "reply": to_dict(reply),
        "thread": await store.reply_thread(reply, limit=50),
        "answers": to_dict(await store.list_answers(reply_id)),
    }


@replies_router.post("/{reply_id}/answer")
async def answer_reply(reply_id: int, body: AnswerBody, store: Store = Depends(get_store)):
    """Ответить человеку с аккаунта, на который он написал."""
    try:
        answer = await send_answer(store, reply_id, body.text, body.entities, source="api")
    except AnswerError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "answer": to_dict(answer)}


@replies_router.post("/{reply_id}/status")
async def set_status(reply_id: int, body: StatusBody, store: Store = Depends(get_store)):
    reply = await store.set_reply_status(reply_id, body.status)
    if not reply:
        raise HTTPException(404, "Reply not found")
    return {"ok": True, "reply": to_dict(reply)}
