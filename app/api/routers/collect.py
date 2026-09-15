from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.api.deps import get_store, require_api_key
from app.api.schemas import CollectChatBody, CollectDmBody, MailingBaseBody
from app.api.serialize import to_dict
from app.store import Store
from app.tg.client import telethon_client
from app.tg.collect import collect_dm_history, collect_from_chat
from app.utils.export import contacts_to_csv, contacts_to_txt, contacts_to_xlsx

router = APIRouter(prefix="/collect", tags=["collect"], dependencies=[Depends(require_api_key)])


async def _pick_account(store: Store, account_id: int | None):
    accounts = [a for a in await store.list_accounts() if a.has_telethon]
    if not accounts:
        raise HTTPException(400, "Нет аккаунтов с session")
    if account_id:
        for a in accounts:
            if a.id == account_id:
                return a
        raise HTTPException(404, "Account not found or no session")
    return accounts[0]


async def _save(store: Store, result, base_name: str, *, kind: str, mode: str, target: str, account_id: int | None):
    suffix = " (стоп)" if getattr(result, "stopped", False) else ""
    base = await store.add_base((base_name + suffix)[:60])
    added = 0
    for item in result.contacts:
        a, _ = await store.add_contacts([item], base.id)
        added += a
    banned = 0
    for item in result.banned:
        reason = result.banned_reasons.get(f"{item.kind}:{item.value}", "banword")
        if await store.add_ban_contact(
            item.kind,
            item.value,
            display=item.display,
            reason=reason,
            source_base_id=base.id,
        ):
            banned += 1
    run = await store.add_collect_run(
        source="api",
        kind=kind,
        mode=mode,
        target=target,
        title=getattr(result, "chat_title", "") or base.name,
        account_id=account_id,
        base_id=base.id,
        added=added,
        banned=banned,
        stopped=bool(getattr(result, "stopped", False)),
        notes="; ".join(getattr(result, "notes", [])[:8]),
    )
    return base, added, banned, run


@router.get("/history")
async def collect_history(
    limit: int = Query(40, ge=1, le=200),
    offset: int = Query(0, ge=0),
    store: Store = Depends(get_store),
):
    runs = await store.list_collect_runs(limit=limit, offset=offset)
    return {"ok": True, "items": to_dict(runs), "limit": limit, "offset": offset}


@router.get("/history/{run_id}")
async def collect_history_one(run_id: int, store: Store = Depends(get_store)):
    run = await store.get_collect_run(run_id)
    if not run:
        raise HTTPException(404, "Collect run not found")
    return {"ok": True, "item": to_dict(run)}


@router.get("/history/{run_id}/export")
async def collect_history_export(
    run_id: int,
    fmt: str = Query("txt", pattern="^(txt|csv|xlsx)$"),
    store: Store = Depends(get_store),
):
    run = await store.get_collect_run(run_id)
    if not run or not run.base_id:
        raise HTTPException(404, "Collect run / base not found")
    contacts = await store.export_contacts(run.base_id)
    safe = (run.base_name or run.title or f"collect_{run.id}").replace(" ", "_")[:40]
    if fmt == "csv":
        data = contacts_to_csv(contacts)
        media = "text/csv"
    elif fmt == "xlsx":
        data = contacts_to_xlsx(contacts)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        data = contacts_to_txt(contacts)
        media = "text/plain"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{safe}.{fmt}"'},
    )


@router.post("/chat")
async def collect_chat(body: CollectChatBody, store: Store = Depends(get_store)):
    if body.mode not in {"all", "writers"}:
        raise HTTPException(400, "mode: all | writers")
    accounts = [a for a in await store.list_accounts() if a.has_telethon]
    if not accounts:
        raise HTTPException(400, "Нет аккаунтов с session")
    if body.account_id:
        accounts = [a for a in accounts if a.id == body.account_id]
        if not accounts:
            raise HTTPException(404, "Account not found or no session")

    last_err = ""
    result = None
    used = None
    banwords = await store.list_banwords()
    for acc in accounts:
        proxy = await store.peek_proxy(acc.id)
        try:
            async with telethon_client(acc.telethon_session, proxy) as client:
                result = await collect_from_chat(
                    client, body.chat, mode=body.mode, banwords=banwords
                )
            used = acc
            break
        except Exception as e:
            last_err = f"{acc.label}: {e}"
            continue
    if result is None or used is None:
        raise HTTPException(502, f"Сбор не удался: {last_err}")

    label = "все участники" if body.mode == "all" else "писавшие"
    name = body.base_name or f"{label}: {result.chat_title or body.chat}"
    base, added, banned, run = await _save(
        store,
        result,
        name,
        kind="chat",
        mode=body.mode,
        target=body.chat,
        account_id=used.id,
    )
    return {
        "ok": True,
        "base": to_dict(base),
        "added": added,
        "banned": banned,
        "stopped": result.stopped,
        "account_id": used.id,
        "run": to_dict(run),
        "notes": result.notes,
    }


@router.post("/dm")
async def collect_dm(body: CollectDmBody, store: Store = Depends(get_store)):
    if body.mode not in {"messaged", "replied"}:
        raise HTTPException(400, "mode: messaged | replied")
    acc = await _pick_account(store, body.account_id)
    proxy = await store.peek_proxy(acc.id)
    banwords = await store.list_banwords()
    try:
        async with telethon_client(acc.telethon_session, proxy) as client:
            result = await collect_dm_history(
                client,
                mode=body.mode,
                banwords=banwords,
                dialog_limit=body.dialog_limit,
            )
    except Exception as e:
        raise HTTPException(502, f"Сбор ЛС не удался: {e}") from e

    label = "кому писали" if body.mode == "messaged" else "кто отвечал"
    name = body.base_name or f"{label}: {acc.label}"
    base, added, banned, run = await _save(
        store,
        result,
        name,
        kind="dm",
        mode=body.mode,
        target=acc.label,
        account_id=acc.id,
    )
    return {
        "ok": True,
        "base": to_dict(base),
        "added": added,
        "banned": banned,
        "stopped": result.stopped,
        "account_id": acc.id,
        "run": to_dict(run),
        "notes": result.notes,
    }


@router.post("/mailing-base")
async def mailing_base(body: MailingBaseBody, store: Store = Depends(get_store)):
    """Итоговая база: без банбазы, blocklist, «кому писали»/sent и дублей."""
    base, stats = await store.build_mailing_base(
        name=body.name or "Итоговая рассылка",
        source_base_id=body.source_base_id,
    )
    run = await store.add_collect_run(
        source="api",
        kind="mailing",
        mode="final",
        target=f"base:{body.source_base_id}" if body.source_base_id else "all",
        title=base.name,
        base_id=base.id,
        added=stats["added"],
        notes=(
            f"ban={stats['excluded_ban']} block={stats['excluded_block']} "
            f"messaged={stats['excluded_messaged']} pending={stats['source_pending']}"
        ),
    )
    return {"ok": True, "base": to_dict(base), "stats": stats, "run": to_dict(run)}
