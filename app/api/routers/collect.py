from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_store, require_api_key
from app.api.schemas import CollectChatBody, CollectDmBody
from app.api.serialize import to_dict
from app.store import Store
from app.tg.client import telethon_client
from app.tg.collect import collect_dm_history, collect_from_chat

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


async def _save(store: Store, result, base_name: str):
    base = await store.add_base(base_name[:60])
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
    return base, added, banned


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
            last_err = str(e)
            continue
    if result is None or used is None:
        raise HTTPException(502, f"Сбор не удался: {last_err}")

    label = "все участники" if body.mode == "all" else "писавшие"
    name = body.base_name or f"{label}: {result.chat_title or body.chat}"
    base, added, banned = await _save(store, result, name)
    return {
        "ok": True,
        "base": to_dict(base),
        "added": added,
        "banned": banned,
        "account_id": used.id,
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
    base, added, banned = await _save(store, result, name)
    return {
        "ok": True,
        "base": to_dict(base),
        "added": added,
        "banned": banned,
        "account_id": acc.id,
        "notes": result.notes,
    }
