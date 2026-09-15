from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import get_store, require_api_key
from app.api.schemas import ProxiesAdd, ProxyBind
from app.api.serialize import to_dict
from app.store import Store
from app.tg.proxy_check import check_proxy
from app.utils.proxy import parse_proxy_blob, parse_proxy_file

router = APIRouter(prefix="/proxies", tags=["proxies"], dependencies=[Depends(require_api_key)])


@router.get("")
async def list_proxies(store: Store = Depends(get_store)):
    items = await store.list_proxies()
    return {"ok": True, "items": to_dict(items), "total": len(items)}


@router.post("")
async def add_proxies_text(body: ProxiesAdd, store: Store = Depends(get_store)):
    items = parse_proxy_blob(body.text)
    if not items:
        raise HTTPException(400, "Не найдено ни одного прокси")
    added, skipped = await store.add_proxies(items)
    return {
        "ok": True,
        "added": added,
        "skipped": skipped,
        "total": len(await store.list_proxies()),
    }


@router.post("/upload")
async def add_proxies_file(file: UploadFile = File(...), store: Store = Depends(get_store)):
    data = await file.read()
    items = parse_proxy_file(data, file.filename or "proxies.txt")
    if not items:
        raise HTTPException(400, "Не найдено ни одного прокси")
    added, skipped = await store.add_proxies(items)
    return {"ok": True, "added": added, "skipped": skipped}


@router.get("/{proxy_id}")
async def get_proxy(proxy_id: int, store: Store = Depends(get_store)):
    proxy = await store.get_proxy(proxy_id)
    if not proxy:
        raise HTTPException(404, "Proxy not found")
    accounts = await store.accounts_for_proxy(proxy_id)
    return {"ok": True, "proxy": to_dict(proxy), "accounts": to_dict(accounts)}


@router.delete("/{proxy_id}")
async def delete_proxy(proxy_id: int, store: Store = Depends(get_store)):
    if not await store.get_proxy(proxy_id):
        raise HTTPException(404, "Proxy not found")
    await store.delete_proxy(proxy_id)
    return {"ok": True}


@router.post("/{proxy_id}/check")
async def check_proxy_api(proxy_id: int, store: Store = Depends(get_store)):
    proxy = await store.get_proxy(proxy_id)
    if not proxy:
        raise HTTPException(404, "Proxy not found")
    ok, detail = await check_proxy(proxy)
    await store.mark_proxy(proxy_id, "ok" if ok else "error", detail)
    return {"ok": True, "valid": ok, "detail": detail, "proxy": to_dict(await store.get_proxy(proxy_id))}


@router.post("/{proxy_id}/bind")
async def bind_proxy(proxy_id: int, body: ProxyBind, store: Store = Depends(get_store)):
    if not await store.get_proxy(proxy_id):
        raise HTTPException(404, "Proxy not found")
    if not await store.get_account(body.account_id):
        raise HTTPException(404, "Account not found")
    await store.bind_proxy(body.account_id, proxy_id, body.bind)
    return {"ok": True, "bound": body.bind}


@router.post("/rebalance")
async def rebalance(store: Store = Depends(get_store)):
    await store.rebalance_proxies()
    return {"ok": True, "detail": "full rebalance done"}


@router.post("/assign-unbound")
async def assign_unbound(store: Store = Depends(get_store)):
    await store.assign_unbound_proxies()
    return {"ok": True, "detail": "unbound proxies assigned"}
