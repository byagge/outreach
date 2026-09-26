from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.deps import get_store, require_api_key
from app.api.schemas import TextCreate, TextUpdate
from app.api.serialize import to_dict
from app.config import TEXTS_DIR
from app.store import Store
from app.utils.entities import prepare_offer_text

router = APIRouter(prefix="/texts", tags=["texts"], dependencies=[Depends(require_api_key)])


@router.get("")
async def list_texts(
    enabled_only: bool = False,
    shared_only: bool = True,
    campaign_id: int | None = None,
    store: Store = Depends(get_store),
):
    """
    По умолчанию — только общие офферы (основная рассылка).
    campaign_id=N — офферы этой кампании.
    shared_only=false без campaign_id — все.
    """
    items = await store.list_texts(
        enabled_only=enabled_only,
        campaign_id=campaign_id,
        shared_only=shared_only if campaign_id is None else False,
    )
    return {"ok": True, "items": to_dict(items), "total": len(items)}


@router.get("/{text_id}")
async def get_text(text_id: int, store: Store = Depends(get_store)):
    item = await store.get_text(text_id)
    if not item:
        raise HTTPException(404, "Text not found")
    return {"ok": True, "text": to_dict(item)}


@router.post("")
async def create_text(body: TextCreate, store: Store = Depends(get_store)):
    if not (body.text or "").strip() and not (body.photo_path or "").strip():
        raise HTTPException(400, "Нужен text или photo_path")
    text, entities = prepare_offer_text(
        body.text,
        body.entities,
        expand_markers=body.expand_emoji_markers,
    )
    item = await store.add_text(
        text,
        entities,
        photo_path=body.photo_path,
        title=body.title or "",
    )
    if body.enabled == 0:
        item = await store.update_text(item.id, enabled=0)
    return {"ok": True, "text": to_dict(item)}


@router.post("/upload")
async def create_text_with_photo(
    text: str = Form(""),
    title: str = Form(""),
    file: UploadFile | None = File(None),
    store: Store = Depends(get_store),
):
    photo_path = ""
    if file is not None:
        n = len(await store.list_texts()) + 1
        dest = TEXTS_DIR / f"api_{n}_{file.filename or 'photo.jpg'}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(await file.read())
        photo_path = str(dest)
    if not text.strip() and not photo_path:
        raise HTTPException(400, "Нужен text или photo")
    text, entities = prepare_offer_text(text, [])
    item = await store.add_text(text, entities, photo_path=photo_path, title=title or "вариант")
    return {"ok": True, "text": to_dict(item)}


@router.patch("/{text_id}")
async def update_text(text_id: int, body: TextUpdate, store: Store = Depends(get_store)):
    data = body.model_dump(exclude_none=True)
    expand = data.pop("expand_emoji_markers", True)
    if expand is None:
        expand = True
    if "text" in data or "entities" in data or "entities_json" in data:
        raw_text = data.get("text")
        if raw_text is None:
            existing = await store.get_text(text_id)
            raw_text = existing.text if existing else ""
        ents = data.pop("entities", None)
        if ents is None and "entities_json" in data:
            try:
                ents = json.loads(data.pop("entities_json") or "[]")
            except json.JSONDecodeError:
                ents = []
                data.pop("entities_json", None)
        elif "entities_json" in data:
            data.pop("entities_json")
        text, entities = prepare_offer_text(
            raw_text or "",
            ents,
            expand_markers=bool(expand),
        )
        data["text"] = text
        data["entities_json"] = json.dumps(entities, ensure_ascii=False)
    item = await store.update_text(text_id, **data)
    if not item:
        raise HTTPException(404, "Text not found")
    return {"ok": True, "text": to_dict(item)}


@router.post("/{text_id}/upload")
async def update_text_photo(
    text_id: int,
    file: UploadFile = File(...),
    store: Store = Depends(get_store),
):
    item = await store.get_text(text_id)
    if not item:
        raise HTTPException(404, "Text not found")
    dest = TEXTS_DIR / f"api_{text_id}_{file.filename or 'photo.jpg'}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(await file.read())
    item = await store.update_text(text_id, photo_path=str(dest))
    return {"ok": True, "text": to_dict(item)}


@router.post("/{text_id}/toggle")
async def toggle_text(text_id: int, store: Store = Depends(get_store)):
    item = await store.get_text(text_id)
    if not item:
        raise HTTPException(404, "Text not found")
    item = await store.update_text(text_id, enabled=0 if item.enabled else 1)
    return {"ok": True, "text": to_dict(item)}


@router.delete("/{text_id}")
async def delete_text(text_id: int, store: Store = Depends(get_store)):
    if not await store.get_text(text_id):
        raise HTTPException(404, "Text not found")
    await store.delete_text(text_id)
    return {"ok": True}
