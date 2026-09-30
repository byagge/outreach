from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.api.deps import get_store, require_api_key
from app.api.schemas import CollectChatBody, CollectDmBody, CollectPremiumBody, MailingBaseBody
from app.api.serialize import to_dict
from app.config import get_settings
from app.store import Store
from app.tg.client import telethon_client
from app.tg.collect import collect_dm_history, collect_from_chat
from app.tg.premium_collect import collect_premium_from_groups
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


async def _save(
    store: Store,
    result,
    base_name: str,
    *,
    kind: str,
    mode: str,
    target: str,
    account_id: int | None,
    isolated: bool = False,
):
    suffix = " (стоп)" if getattr(result, "stopped", False) else ""
    prefix = "⊕ " if isolated else ""
    base = await store.add_base(
        (prefix + base_name + suffix)[:60],
        isolated=1 if isolated else 0,
        enabled=0 if isolated else 1,
    )
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
    run_mode = f"separate:{mode}" if isolated and mode else ("separate" if isolated else mode)
    run = await store.add_collect_run(
        source="api",
        kind=kind,
        mode=run_mode,
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
        isolated=bool(body.isolated),
    )
    return {
        "ok": True,
        "base": to_dict(base),
        "added": added,
        "banned": banned,
        "stopped": result.stopped,
        "isolated": bool(body.isolated),
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
        isolated=bool(body.isolated),
    )
    return {
        "ok": True,
        "base": to_dict(base),
        "added": added,
        "banned": banned,
        "stopped": result.stopped,
        "isolated": bool(body.isolated),
        "account_id": acc.id,
        "run": to_dict(run),
        "notes": result.notes,
    }


@router.post("/premium")
async def collect_premium(body: CollectPremiumBody, store: Store = Depends(get_store)):
    """★ чаты → полные сообщения → 3 базы: premium / coders / other."""
    lang = (body.language or "ru").lower().strip()
    if lang not in {"ru", "en"}:
        raise HTTPException(400, "language: ru | en")
    acc = await _pick_account(store, body.account_id)
    cfg = get_settings()
    if body.use_llm is False:
        raise HTTPException(
            400,
            "use_llm=false больше не поддерживается — нужен смысловой LLM",
        )
    use_llm = True
    if not (cfg.llm_enabled and cfg.llm_base_url and cfg.llm_model and (
        cfg.llm_api_key or "11434" in cfg.llm_base_url or "localhost" in cfg.llm_base_url
    )):
        raise HTTPException(
            400,
            "Задайте LLM_ENABLED + LLM_BASE_URL + LLM_MODEL + LLM_API_KEY "
            "(OpenAI / Anthropic / OpenRouter)",
        )
    discover = (
        cfg.premium_discover_open
        if body.discover_open is None
        else bool(body.discover_open)
    )
    proxy = await store.peek_proxy(acc.id)
    banwords = await store.list_banwords()
    try:
        async with telethon_client(acc.telethon_session, proxy) as client:
            result = await collect_premium_from_groups(
                client,
                language=lang,
                banwords=banwords,
                messages_per_chat=body.messages_per_chat,
                max_msgs_per_user=int(cfg.premium_max_msgs_per_user),
                llm_base_url=cfg.llm_base_url,
                llm_model=cfg.llm_model,
                llm_api_key=cfg.llm_api_key,
                llm_model_refine=cfg.llm_model_refine,
                use_llm=use_llm,
                discover_open=discover,
                max_discover_join=body.max_discover_join,
                premium_threshold=int(cfg.premium_score_threshold),
                chat_min_score=int(cfg.premium_chat_min_score),
                chat_top_k=int(cfg.premium_chat_top_k),
                batch_size=int(cfg.llm_batch_size),
                max_posts_to_llm=int(cfg.llm_max_posts),
                scan_all_chats=bool(cfg.premium_scan_all_chats),
            )
    except Exception as e:
        raise HTTPException(502, f"Premium collect failed: {e}") from e

    lang_label = "русский" if lang == "ru" else "english"
    stamp = acc.label[:20]
    suffix = " (стоп)" if result.stopped else ""

    async def _bucket(name: str, items, *, enabled: int):
        base = await store.add_base(
            (name + suffix)[:60], isolated=1, enabled=enabled
        )
        added = 0
        for item in items:
            a, _ = await store.add_contacts([item], base.id)
            added += a
        return base, added

    prem_base, prem_n = await _bucket(
        f"★ Дорогие [{lang_label}]: {stamp}", result.premium, enabled=1
    )
    cod_base, cod_n = await _bucket(
        f"Кодеры [{lang_label}]: {stamp}", result.coders, enabled=0
    )
    oth_base, oth_n = await _bucket(
        f"Прочие [{lang_label}]: {stamp}", result.other, enabled=0
    )

    banned = 0
    for item in result.banned:
        reason = result.banned_reasons.get(f"{item.kind}:{item.value}", "banword")
        if await store.add_ban_contact(
            item.kind,
            item.value,
            display=item.display,
            reason=reason,
            source_base_id=prem_base.id,
        ):
            banned += 1

    run = await store.add_collect_run(
        source="api",
        kind="premium",
        mode=f"lang:{lang}",
        target=acc.label,
        title=f"★ {prem_n} / код {cod_n} / др {oth_n}",
        account_id=acc.id,
        base_id=prem_base.id,
        added=prem_n + cod_n + oth_n,
        banned=banned,
        stopped=result.stopped,
        notes="; ".join(result.notes[:8])
        + f"; bases={prem_base.id},{cod_base.id},{oth_base.id}",
    )
    return {
        "ok": True,
        "language": lang,
        "account_id": acc.id,
        "chats_premium": result.chats_premium,
        "chats_skipped": result.chats_skipped,
        "chats_joined": result.chats_joined,
        "chats_scanned": result.chats_scanned,
        "premium_chat_titles": result.premium_chat_titles[:30],
        "lang_skipped": result.lang_skipped,
        "stopped": result.stopped,
        "premium": {"base": to_dict(prem_base), "added": prem_n},
        "coders": {"base": to_dict(cod_base), "added": cod_n},
        "other": {"base": to_dict(oth_base), "added": oth_n},
        "banned": banned,
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
