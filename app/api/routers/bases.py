from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.ai.contacts import parse_contacts_file, parse_lines, parse_xlsx_all_sheets
from app.api.deps import get_store, require_api_key
from app.api.schemas import BaseCreate, BaseRename, ContactsAdd
from app.api.serialize import to_dict
from app.store import Store
from app.utils.export import contacts_to_csv, contacts_to_txt, contacts_to_xlsx

router = APIRouter(prefix="/bases", tags=["bases"], dependencies=[Depends(require_api_key)])


@router.get("")
async def list_bases(store: Store = Depends(get_store)):
    bases = await store.list_bases()
    items = []
    for b in bases:
        row = to_dict(b)
        row["stats"] = await store.base_stats(b.id)
        items.append(row)
    return {"ok": True, "items": items, "total": len(items)}


@router.post("")
async def create_base(body: BaseCreate, store: Store = Depends(get_store)):
    base = await store.add_base(body.name)
    return {"ok": True, "base": to_dict(base)}


@router.get("/{base_id}")
async def get_base(base_id: int, store: Store = Depends(get_store)):
    base = await store.get_base(base_id)
    if not base:
        raise HTTPException(404, "Base not found")
    stats = await store.base_stats(base_id)
    preview = await store.list_contacts_for_base(base_id, page=0, per_page=20)
    return {"ok": True, "base": to_dict(base), "stats": stats, "preview": to_dict(preview)}


@router.patch("/{base_id}")
async def rename_base(base_id: int, body: BaseRename, store: Store = Depends(get_store)):
    base = await store.rename_base(base_id, body.name)
    if not base:
        raise HTTPException(404, "Base not found")
    return {"ok": True, "base": to_dict(base)}


@router.post("/{base_id}/toggle")
async def toggle_base(base_id: int, store: Store = Depends(get_store)):
    base = await store.toggle_base(base_id)
    if not base:
        raise HTTPException(404, "Base not found")
    return {"ok": True, "base": to_dict(base)}


@router.delete("/{base_id}")
async def delete_base(base_id: int, store: Store = Depends(get_store)):
    if not await store.get_base(base_id):
        raise HTTPException(404, "Base not found")
    await store.delete_base(base_id)
    return {"ok": True}


@router.get("/{base_id}/contacts")
async def list_base_contacts(
    base_id: int,
    status: str | None = None,
    page: int = Query(0, ge=0),
    per_page: int = Query(50, ge=1, le=500),
    store: Store = Depends(get_store),
):
    if not await store.get_base(base_id):
        raise HTTPException(404, "Base not found")
    items = await store.list_contacts_for_base(base_id, status=status, page=page, per_page=per_page)
    return {"ok": True, "items": to_dict(items), "page": page, "per_page": per_page}


@router.post("/{base_id}/contacts")
async def add_contacts_text(base_id: int, body: ContactsAdd, store: Store = Depends(get_store)):
    if not await store.get_base(base_id):
        raise HTTPException(404, "Base not found")
    parsed = parse_lines(body.text)
    usable = [c for c in parsed.contacts if c.kind != "unknown"]
    added, skipped = await store.add_contacts(usable, base_id)
    return {"ok": True, "added": added, "skipped": skipped, "notes": parsed.notes}


@router.post("/{base_id}/import")
async def import_file(
    base_id: int,
    file: UploadFile = File(...),
    multi_sheet: bool = True,
    store: Store = Depends(get_store),
):
    if not await store.get_base(base_id):
        raise HTTPException(404, "Base not found")
    raw = await file.read()
    name = (file.filename or "file.txt").lower()
    created_bases = []
    if multi_sheet and name.endswith((".xlsx", ".xlsm")):
        sheets = parse_xlsx_all_sheets(raw)
        if len(sheets) > 1:
            first_name, first = next(iter(sheets.items()))
            await store.rename_base(base_id, first_name[:60])
            usable = [c for c in first.contacts if c.kind != "unknown"]
            added, skipped = await store.add_contacts(usable, base_id)
            total_added, total_skipped = added, skipped
            for sheet_name, result in list(sheets.items())[1:]:
                b = await store.add_base(sheet_name[:60])
                usable = [c for c in result.contacts if c.kind != "unknown"]
                a, s = await store.add_contacts(usable, b.id)
                total_added += a
                total_skipped += s
                created_bases.append(to_dict(b))
            return {
                "ok": True,
                "added": total_added,
                "skipped": total_skipped,
                "sheets": len(sheets),
                "created_bases": created_bases,
            }
    parsed = parse_contacts_file(raw, file.filename or "file.txt")
    usable = [c for c in parsed.contacts if c.kind != "unknown"]
    added, skipped = await store.add_contacts(usable, base_id)
    return {"ok": True, "added": added, "skipped": skipped, "notes": parsed.notes}


@router.get("/{base_id}/export")
async def export_base(
    base_id: int,
    fmt: str = Query("txt", pattern="^(txt|csv|xlsx)$"),
    store: Store = Depends(get_store),
):
    base = await store.get_base(base_id)
    if not base:
        raise HTTPException(404, "Base not found")
    contacts = await store.export_contacts(base_id)
    safe = base.name.replace(" ", "_")[:40]
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
