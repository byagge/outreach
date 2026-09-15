from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import get_store, require_api_key
from app.api.schemas import AccountCreate, AccountPause, AccountUpdate
from app.api.serialize import to_dict
from app.config import SESSIONS_DIR
from app.store import Store
from app.tg.client import inspect_session
from app.utils.sessions import detect_session_kind
from app.utils.work_hours import parse_work_hours

router = APIRouter(prefix="/accounts", tags=["accounts"], dependencies=[Depends(require_api_key)])


@router.get("")
async def list_accounts(store: Store = Depends(get_store)):
    items = await store.list_accounts()
    return {"ok": True, "items": to_dict(items), "total": len(items)}


@router.post("")
async def create_account(body: AccountCreate, store: Store = Depends(get_store)):
    acc = await store.add_account(body.label.strip())
    return {"ok": True, "account": to_dict(acc)}


@router.get("/{account_id}")
async def get_account(account_id: int, store: Store = Depends(get_store)):
    acc = await store.get_account(account_id)
    if not acc:
        raise HTTPException(404, "Account not found")
    proxies = await store.proxies_for_account(account_id)
    return {"ok": True, "account": to_dict(acc), "proxies": to_dict(proxies)}


@router.patch("/{account_id}")
async def update_account(account_id: int, body: AccountUpdate, store: Store = Depends(get_store)):
    data = body.model_dump(exclude_none=True)
    if data.get("work_start") is not None and data.get("work_end") is not None:
        if data["work_start"] or data["work_end"]:
            parsed = parse_work_hours(f"{data['work_start']}-{data['work_end']}")
            if parsed is None:
                raise HTTPException(400, "Неверный формат рабочих часов HH:MM-HH:MM")
            data["work_start"], data["work_end"] = parsed
    acc = await store.update_account(account_id, **data)
    if not acc:
        raise HTTPException(404, "Account not found")
    return {"ok": True, "account": to_dict(acc)}


@router.delete("/{account_id}")
async def delete_account(account_id: int, store: Store = Depends(get_store)):
    if not await store.get_account(account_id):
        raise HTTPException(404, "Account not found")
    await store.delete_account(account_id)
    return {"ok": True}


@router.post("/{account_id}/toggle-assigned")
async def toggle_assigned(account_id: int, store: Store = Depends(get_store)):
    acc = await store.toggle_assigned(account_id)
    if not acc:
        raise HTTPException(404, "Account not found")
    return {"ok": True, "account": to_dict(acc)}


@router.post("/{account_id}/pause")
async def pause_account(account_id: int, body: AccountPause, store: Store = Depends(get_store)):
    if not await store.get_account(account_id):
        raise HTTPException(404, "Account not found")
    await store.pause_account(account_id, body.seconds, body.error)
    return {"ok": True, "account": to_dict(await store.get_account(account_id))}


@router.post("/{account_id}/session")
async def upload_session(
    account_id: int,
    file: UploadFile = File(...),
    store: Store = Depends(get_store),
):
    acc = await store.get_account(account_id)
    if not acc:
        raise HTTPException(404, "Account not found")
    name = (file.filename or "telethon.session").lower()
    if not name.endswith(".session"):
        raise HTTPException(400, "Нужен файл .session (Telethon)")
    dest_dir = SESSIONS_DIR / str(account_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "telethon.session"
    dest.write_bytes(await file.read())
    kind = detect_session_kind(dest)
    if kind == "pyrogram":
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Это Pyrogram session — нужен Telethon")
    fields: dict = {"telethon_session": str(dest)}
    note = "session saved"
    proxy = (await store.proxies_for_account(account_id) or [None])[0]
    try:
        info = await inspect_session(dest, proxy)
        fields.update(
            user_id=info["user_id"],
            username=info["username"],
            phone=info["phone"],
        )
        note = f"ok as {info.get('first_name')} (@{info.get('username') or '-'})"
    except Exception as e:
        note = f"saved but open failed: {e}"
    acc = await store.update_account(account_id, **fields)
    return {"ok": True, "account": to_dict(acc), "detail": note, "kind": kind}


@router.get("/{account_id}/proxies")
async def account_proxies(account_id: int, store: Store = Depends(get_store)):
    if not await store.get_account(account_id):
        raise HTTPException(404, "Account not found")
    return {"ok": True, "items": to_dict(await store.proxies_for_account(account_id))}


@router.get("/{account_id}/peek-proxy")
async def peek_proxy(account_id: int, store: Store = Depends(get_store)):
    return {"ok": True, "proxy": to_dict(await store.peek_proxy(account_id))}


@router.post("/{account_id}/next-proxy")
async def next_proxy(account_id: int, store: Store = Depends(get_store)):
    return {"ok": True, "proxy": to_dict(await store.next_proxy(account_id))}
