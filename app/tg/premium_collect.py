"""
Lead Intelligence — лучшее качество.

- Полный deep-scan групп (тысячи сообщений, не 10–20)
- Полные тексты постов в LLM (без обрезки смысла)
- Сильная модель: 1 вызов = досье + score
- Экономия только: выкинуть «ок/лол», точные дубли, пустые профили; мелкий батч 2–3
"""

from __future__ import annotations

from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, User

from app.ai.contacts import Classified
from app.ai.intel import IntelConfig
from app.ai.intel.chat_rank import rank_chat
from app.ai.intel.pipeline import run_people_intelligence
from app.ai.intel.schema import PersonRaw
from app.ai.llm import llm_configured
from app.ai.qualify import LeadProfile, language_ok
from app.tg.collect import PremiumCollectResult, _cancelled, _key, _user_classified
from app.utils.banwords import contains_banword

SEARCH_QUERIES_RU = (
    "ищу клиентов трафик",
    "нужен чаттер",
    "ищу медиабайера",
    "ведение аккаунтов",
    "слоты модели",
    "куплю трафик",
    "ищу партнёра на оффер",
)
SEARCH_QUERIES_EN = (
    "looking for clients traffic",
    "need chatter hire",
    "media buyer needed",
    "account manager slots",
    "buy traffic offer",
    "looking for partner offer",
)


def _is_group_dialog(entity) -> bool:
    if isinstance(entity, Chat):
        return True
    if isinstance(entity, Channel):
        return bool(
            getattr(entity, "megagroup", False) or getattr(entity, "gigagroup", False)
        )
    return False


async def _chat_about(client: TelegramClient, entity) -> str:
    try:
        if isinstance(entity, Channel):
            from telethon.tl.functions.channels import GetFullChannelRequest

            full = await client(GetFullChannelRequest(entity))
            return (getattr(full.full_chat, "about", None) or "")[:800]
        if isinstance(entity, Chat):
            from telethon.tl.functions.messages import GetFullChatRequest

            full = await client(GetFullChatRequest(entity.id))
            return (getattr(full.full_chat, "about", None) or "")[:800]
    except Exception:
        return ""
    return ""


async def _pull_posts(
    client: TelegramClient, entity, *, limit: int, max_keep: int
) -> list[str]:
    out: list[str] = []
    try:
        async for msg in client.iter_messages(entity, limit=limit):
            text = (msg.message or "").strip()
            if text:
                out.append(text)
            if len(out) >= max_keep:
                break
    except Exception:
        pass
    return out


async def discover_open_chats(
    client: TelegramClient,
    *,
    language: str = "ru",
    max_join: int = 8,
    should_stop=None,
    on_progress=None,
) -> int:
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.tl.functions.contacts import SearchRequest

    queries = SEARCH_QUERIES_RU if language == "ru" else SEARCH_QUERIES_EN
    seen: set[int] = set()
    candidates: list = []
    for q in queries:
        if _cancelled(should_stop):
            break
        if on_progress:
            await on_progress(f"поиск: {q[:36]}")
        try:
            res = await client(SearchRequest(q=q, limit=20))
        except Exception:
            continue
        for ch in getattr(res, "chats", []) or []:
            cid = int(getattr(ch, "id", 0) or 0)
            if not cid or cid in seen:
                continue
            if not isinstance(ch, Channel) or not (getattr(ch, "username", None) or "").strip():
                continue
            seen.add(cid)
            candidates.append(ch)
    joins = 0
    for ch in candidates:
        if joins >= max_join or _cancelled(should_stop):
            break
        try:
            if on_progress:
                await on_progress(f"join @{getattr(ch, 'username', '')}")
            await client(JoinChannelRequest(ch))
            joins += 1
        except Exception:
            pass
    return joins


async def collect_premium_from_groups(
    client: TelegramClient,
    *,
    language: str = "ru",
    banwords: list[str] | None = None,
    messages_per_chat: int = 8000,
    max_msgs_per_user: int = 60,
    discover_open: bool = True,
    max_discover_join: int = 8,
    llm_base_url: str = "",
    llm_model: str = "",
    llm_api_key: str = "",
    llm_model_refine: str = "",
    use_llm: bool = True,
    premium_threshold: int = 70,
    chat_min_score: int = 0,
    chat_top_k: int = 80,
    batch_size: int = 3,
    max_posts_to_llm: int = 50,
    scan_all_chats: bool = True,
    should_stop=None,
    on_progress=None,
) -> PremiumCollectResult:
    if not use_llm or not (
        llm_configured() or (llm_base_url and llm_model and llm_api_key)
    ):
        raise RuntimeError(
            "Нужен LLM API. Рекомендуем gpt-4o или claude-sonnet "
            "(качество важнее mini)."
        )

    words = banwords or []
    result = PremiumCollectResult()
    result.notes.append(f"lang={language}")
    result.notes.append("mode=quality-fullscan")

    async def _progress(msg: str) -> None:
        if on_progress:
            await on_progress(msg)

    if discover_open and max_discover_join > 0:
        await _progress("поиск площадок операторов…")
        try:
            result.chats_joined = await discover_open_chats(
                client,
                language=language,
                max_join=max_discover_join,
                should_stop=should_stop,
                on_progress=_progress,
            )
            result.notes.append(f"joined={result.chats_joined}")
        except Exception as e:
            result.notes.append(f"discover:{str(e)[:60]}")

    groups: list = []
    async for dialog in client.iter_dialogs(limit=None):
        if _cancelled(should_stop):
            result.stopped = True
            break
        if _is_group_dialog(dialog.entity):
            groups.append(dialog)
    result.notes.append(f"groups={len(groups)}")

    # Выбор чатов: по умолчанию ВСЕ. Если слишком много — LLM-rank по большому сэмплу.
    keep: list[tuple[object, str, int]] = []
    if scan_all_chats and len(groups) <= chat_top_k:
        await _progress(f"deep-scan ВСЕХ {len(groups)} групп…")
        for d in groups:
            title = (d.name or getattr(d.entity, "title", None) or "?")[:120]
            keep.append((d, title, 100))
    else:
        await _progress(
            f"групп {len(groups)} > {chat_top_k}: LLM rank по ~120 постам, потом deep-scan"
        )
        ranked: list[tuple[int, object, str]] = []
        for gi, dialog in enumerate(groups, 1):
            if _cancelled(should_stop):
                result.stopped = True
                break
            entity = dialog.entity
            title = (dialog.name or getattr(entity, "title", None) or "?")[:120]
            await _progress(f"rank {gi}/{len(groups)}: {title[:32]}")
            about = await _chat_about(client, entity)
            # большой сэмпл для смысла — не 10–20
            samples = await _pull_posts(client, entity, limit=400, max_keep=120)
            cr = await rank_chat(
                chat_id=int(getattr(entity, "id", 0) or dialog.id),
                title=title,
                about=about,
                posts=samples,
                language=language,
                llm_base_url=llm_base_url,
                llm_model=llm_model,
                llm_api_key=llm_api_key,
            )
            ranked.append((cr.score, dialog, title))
        ranked.sort(key=lambda x: x[0], reverse=True)
        for score, dialog, title in ranked[:chat_top_k]:
            if chat_min_score and score < chat_min_score:
                continue
            keep.append((dialog, title, score))
        if not keep:
            keep = [(d, t, s) for s, d, t in ranked[:chat_top_k]]

    result.chats_premium = len(keep)
    result.chats_skipped = max(0, len(groups) - len(keep))
    result.premium_chat_titles = [f"{t}({s})" for _, t, s in keep[:20]]
    result.notes.append(f"deep_chats={len(keep)}")
    if not keep:
        return result

    profiles: dict[int, PersonRaw] = {}
    user_map: dict[int, User] = {}
    banned_ids: dict[int, str] = {}

    for gi, (dialog, title, score) in enumerate(keep, 1):
        if _cancelled(should_stop):
            result.stopped = True
            break
        entity = dialog.entity
        result.chats_scanned += 1
        await _progress(
            f"FULL scan {gi}/{len(keep)}: {title[:34]} · people {len(profiles)}"
        )
        n = 0
        try:
            # полный проход истории (не выход после 10–20)
            async for msg in client.iter_messages(entity, limit=messages_per_chat):
                if _cancelled(should_stop):
                    result.stopped = True
                    break
                n += 1
                if n % 500 == 0:
                    await _progress(
                        f"FULL {gi}/{len(keep)} msg {n} · people {len(profiles)}"
                    )
                sender = await msg.get_sender()
                if not isinstance(sender, User) or sender.bot or sender.deleted:
                    continue
                user_map[sender.id] = sender
                raw = profiles.get(sender.id)
                if raw is None:
                    raw = PersonRaw(
                        user_id=sender.id,
                        username=(sender.username or "").lower(),
                        first_name=sender.first_name or "",
                        last_name=sender.last_name or "",
                    )
                    profiles[sender.id] = raw
                if title and title not in raw.chat_titles:
                    raw.chat_titles.append(title)
                text = (msg.message or "").strip()
                if not text:
                    continue
                if words:
                    hit = contains_banword(text, words)
                    if hit:
                        banned_ids.setdefault(sender.id, hit)
                if len(raw.posts) < max_msgs_per_user:
                    raw.posts.append(text)  # полный текст
        except Exception as e:
            result.notes.append(f"skip:{title[:24]}:{str(e)[:50]}")
        if result.stopped:
            break

    budget = 150
    for uid, raw in profiles.items():
        if budget <= 0 or _cancelled(should_stop):
            break
        if raw.bio or len(raw.posts) >= 4:
            continue
        try:
            from telethon.tl.functions.users import GetFullUserRequest

            fu = await client(GetFullUserRequest(await client.get_input_entity(uid)))
            about = getattr(fu.full_user, "about", None) or ""
            if about:
                raw.bio = about[:800]
            budget -= 1
        except Exception:
            budget -= 1

    people: list[PersonRaw] = []
    for raw in profiles.values():
        lp = LeadProfile(
            user_id=raw.user_id,
            username=raw.username,
            first_name=raw.first_name,
            last_name=raw.last_name,
            bio=raw.bio,
            messages=raw.posts,
            chat_titles=raw.chat_titles,
        )
        if not language_ok(lp, language):
            result.lang_skipped += 1
            continue
        people.append(raw)

    people.sort(
        key=lambda p: (len(p.chat_titles), sum(len(x) for x in p.posts[:20])),
        reverse=True,
    )

    cfg = IntelConfig(
        language=language,
        premium_threshold=premium_threshold,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        chat_top_k=chat_top_k,
        batch_size=batch_size,
        max_posts_to_llm=max_posts_to_llm,
        scan_all_chats=scan_all_chats,
        enable_refine=False,
    )

    await _progress(f"quality LLM: {len(people)} людей, полные посты…")
    verdicts, stats = await run_people_intelligence(
        people,
        cfg,
        should_stop=lambda: _cancelled(should_stop),
        on_progress=_progress,
    )
    result.notes.append(
        f"empty_skip={stats.triage_skipped} batches={stats.llm_batches} "
        f"llm_ppl={stats.llm_people} ~chars={stats.approx_input_chars}"
    )

    seen_keys: set[tuple[str, str]] = set()
    for raw in people:
        if _cancelled(should_stop):
            result.stopped = True
            break
        v = verdicts.get(raw.user_id)
        if not v:
            continue
        user = user_map.get(raw.user_id)
        if not user:
            continue
        item = _user_classified(user)
        if not item:
            continue
        k = _key(item)
        if k in seen_keys:
            continue
        seen_keys.add(k)
        if raw.user_id in banned_ids:
            result.banned.append(item)
            result.banned_reasons[f"{item.kind}:{item.value}"] = (
                f"banword: {banned_ids[raw.user_id]}"
            )
            continue
        item.confidence = v.score / 100.0
        item.reason = f"{v.bucket}:{v.score} {v.reason}"
        item.extra = v.extra
        if v.bucket == "premium":
            result.premium.append(item)
        elif v.bucket == "coders":
            result.coders.append(item)
        else:
            result.other.append(item)

    result.premium.sort(key=lambda c: c.confidence, reverse=True)
    result.notes.append(
        f"★{len(result.premium)} coders={len(result.coders)} other={len(result.other)}"
    )
    await _progress(
        f"готово ★{len(result.premium)} / код {len(result.coders)} / др {len(result.other)}"
    )
    return result
