from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.ai.contacts import parse_lines
from app.api.deps import get_store, require_api_key
from app.api.schemas import ContactFinish, ContactsAdd
from app.api.serialize import to_dict
from app.store import Store

router = APIRouter(prefix="/contacts", tags=["contacts"], dependencies=[Depends(require_api_key)])


@router.get("")
async def list_contacts(
    status: str | None = None,
    page: int = Query(0, ge=0),
    per_page: int = Query(50, ge=1, le=500),
    store: Store = Depends(get_store),
):
    items = await store.list_contacts(status=status, page=page, per_page=per_page)
    return {"ok": True, "items": to_dict(items), "page": page, "per_page": per_page}


@router.get("/kinds")
async def kind_counts(store: Store = Depends(get_store)):
    return {"ok": True, "kinds": await store.contact_kind_counts()}


@router.post("")
async def add_contacts(body: ContactsAdd, store: Store = Depends(get_store)):
    base_id = body.base_id or await store.default_base_id()
    parsed = parse_lines(body.text)
    usable = [c for c in parsed.contacts if c.kind != "unknown"]
    added, skipped = await store.add_contacts(usable, base_id)
    return {"ok": True, "added": added, "skipped": skipped, "base_id": base_id}


@router.post("/claim")
async def claim_contact(store: Store = Depends(get_store)):
    contact = await store.claim_contact()
    return {"ok": True, "contact": to_dict(contact)}


@router.post("/{contact_id}/finish")
async def finish_contact(contact_id: int, body: ContactFinish, store: Store = Depends(get_store)):
    await store.finish_contact(
        contact_id,
        body.status,
        account_id=body.account_id,
        text_id=body.text_id,
        error=body.error,
    )
    return {"ok": True}


@router.post("/{contact_id}/release")
async def release_contact(contact_id: int, store: Store = Depends(get_store)):
    await store.release_contact(contact_id)
    return {"ok": True}


@router.post("/release-stuck")
async def release_stuck(store: Store = Depends(get_store)):
    n = await store.release_stuck_sending()
    return {"ok": True, "released": n}


@router.post("/reset-errors")
async def reset_errors(store: Store = Depends(get_store)):
    n = await store.reset_errors_to_pending()
    return {"ok": True, "reset": n}


@router.delete("")
async def clear_contacts(
    only_pending: bool = False,
    store: Store = Depends(get_store),
):
    n = await store.clear_contacts(only_pending=only_pending)
    return {"ok": True, "deleted": n}
