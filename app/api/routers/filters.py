from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.ai.contacts import parse_lines
from app.api.deps import get_store, require_api_key
from app.api.schemas import BanContactAdd, BanwordsAdd, BlocklistAdd
from app.api.serialize import to_dict
from app.store import Store

router = APIRouter(tags=["filters"], dependencies=[Depends(require_api_key)])


@router.get("/blocklist")
async def list_blocklist(
    page: int = Query(0, ge=0),
    per_page: int = Query(50, ge=1, le=500),
    store: Store = Depends(get_store),
):
    items = await store.list_blocklist(page=page, per_page=per_page)
    return {"ok": True, "items": to_dict(items)}


@router.post("/blocklist")
async def add_blocklist(body: BlocklistAdd, store: Store = Depends(get_store)):
    parsed = parse_lines(body.text)
    usable = [c for c in parsed.contacts if c.kind != "unknown"]
    added, skipped = await store.add_blocklist(usable, note=body.note)
    return {"ok": True, "added": added, "skipped": skipped}


@router.delete("/blocklist/{block_id}")
async def remove_block(block_id: int, store: Store = Depends(get_store)):
    await store.remove_block(block_id)
    return {"ok": True}


@router.get("/banwords")
async def list_banwords(store: Store = Depends(get_store)):
    words = await store.list_banwords()
    return {"ok": True, "words": words, "total": len(words)}


@router.post("/banwords")
async def add_banwords(body: BanwordsAdd, store: Store = Depends(get_store)):
    added, skipped = await store.add_banwords(body.words)
    return {"ok": True, "added": added, "skipped": skipped, "words": await store.list_banwords()}


@router.delete("/banwords/{word}")
async def remove_banword(word: str, store: Store = Depends(get_store)):
    await store.remove_banword(word)
    return {"ok": True, "words": await store.list_banwords()}


@router.get("/ban-contacts")
async def list_ban_contacts(
    page: int = Query(0, ge=0),
    per_page: int = Query(50, ge=1, le=500),
    store: Store = Depends(get_store),
):
    items = await store.list_ban_contacts(page=page, per_page=per_page)
    total = await store.count_ban_contacts()
    return {"ok": True, "items": to_dict(items), "total": total, "page": page}


@router.post("/ban-contacts")
async def add_ban_contact(body: BanContactAdd, store: Store = Depends(get_store)):
    ok = await store.add_ban_contact(
        body.kind,
        body.value,
        display=body.display,
        reason=body.reason,
        source_base_id=body.source_base_id,
    )
    if not ok:
        raise HTTPException(409, "Already in ban base")
    return {"ok": True}


@router.delete("/ban-contacts/{ban_id}")
async def remove_ban_contact(ban_id: int, store: Store = Depends(get_store)):
    ok = await store.remove_ban_contact(ban_id)
    if not ok:
        raise HTTPException(404, "Not found")
    return {"ok": True}


@router.delete("/ban-contacts")
async def clear_ban_contacts(store: Store = Depends(get_store)):
    n = await store.clear_ban_contacts()
    return {"ok": True, "deleted": n}
