from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from html import escape

from telethon.errors import (
    AuthKeyUnregisteredError,
    FloodWaitError,
    InputUserDeactivatedError,
    PeerFloodError,
    PeerIdInvalidError,
    UserPrivacyRestrictedError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)

from app.ai.brain import between_messages, plan_send
from app.config import get_settings
from app.jobs.coordinator import coordinator
from app.jobs.runtime import LogSink, runtime
from app.models import Account, OutreachSettings
from app.store import Store
from app.tg.client import telethon_client
from app.tg.send import send_human
from app.ui.emoji import pe
from app.utils.work_hours import in_work_hours

log = logging.getLogger("outreach.job")

SKIP_ERRORS = (
    UserPrivacyRestrictedError,
    UsernameNotOccupiedError,
    UsernameInvalidError,
    InputUserDeactivatedError,
    PeerIdInvalidError,
)

SKIP_MSG_MARKERS = (
    "это бот",
    "аккаунт удалён",
    "номер не найден",
    "неизвестный тип контакта",
    "пустой оффер",
)


def _pause_left(acc: Account) -> float:
    if not acc.pause_until:
        return 0.0
    try:
        until = datetime.fromisoformat(acc.pause_until)
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return max(0.0, (until - datetime.now(timezone.utc)).total_seconds())
    except ValueError:
        return 0.0


def _err_text(exc: BaseException) -> str:
    text = str(exc) or exc.__class__.__name__
    return text[:400]


def _account_delays(acc: Account, settings: OutreachSettings) -> tuple[int, int]:
    lo = acc.delay_min if acc.delay_min is not None else settings.delay_min
    hi = acc.delay_max if acc.delay_max is not None else settings.delay_max
    return max(1, int(lo)), max(max(1, int(lo)), int(hi))


async def _sleep_cancel(seconds: float) -> bool:
    left = max(0.0, seconds)
    while left > 0:
        if runtime.cancelled("outreach", 0):
            return True
        step = min(1.0, left)
        await asyncio.sleep(step)
        left -= step
    return runtime.cancelled("outreach", 0)


async def _account_worker(store: Store, account_id: int, sink: LogSink) -> None:
    proxy = None
    sends_on_proxy = 0
    tz = get_settings().tz

    while not runtime.cancelled("outreach", 0):
        settings = await store.outreach_settings()
        acc = await store.get_account(account_id)
        if not acc or not acc.telethon_session:
            return
        if not acc.assigned:
            if await _sleep_cancel(2.5):
                return
            continue

        if not in_work_hours(acc.work_start, acc.work_end, tz):
            await store.update_account(account_id, status="idle")
            if await _sleep_cancel(30):
                return
            continue

        wait = _pause_left(acc)
        if wait > 0:
            await store.update_account(account_id, status="paused")
            if await _sleep_cancel(min(wait, 20)):
                return
            continue

        texts = await store.list_texts(enabled_only=True)
        usable = [t for t in texts if (t.text or "").strip() or (t.photo_path or "").strip()]
        if not usable:
            if await _sleep_cancel(3):
                return
            continue

        contact = await store.claim_contact()
        if not contact:
            await store.update_account(account_id, status="idle")
            if settings.continuous:
                if await _sleep_cancel(5):
                    return
                continue
            return

        rotate_every = max(1, settings.rotate_proxy_every)
        if proxy is None or sends_on_proxy >= rotate_every:
            proxy = await store.next_proxy(account_id)
            sends_on_proxy = 0

        try:
            plan = plan_send(
                contact,
                usable,
                acc,
                proxy,
                sent_count=acc.sent_count,
                typing=settings.typing,
                variant_mode=settings.variant_mode,
            )
        except RuntimeError as e:
            await store.release_contact(contact.id)
            await sink.emit(escape(_err_text(e)), level="warn")
            if await _sleep_cancel(3):
                return
            continue

        await sink.emit(f"{escape(acc.label)}: {escape(plan.think)}")
        await store.update_account(account_id, status="running", last_error="")

        try:
            await coordinator.wait_between_accounts(settings)
            async with telethon_client(acc.telethon_session, proxy) as client:
                await send_human(
                    client,
                    contact,
                    plan.text,
                    typing_seconds=plan.typing_seconds,
                    pre_pause=plan.pre_pause,
                )
            await coordinator.mark_sent()
            await store.finish_contact(
                contact.id,
                "sent",
                account_id=account_id,
                text_id=plan.text.id,
            )
            await store.add_send(
                contact_id=contact.id,
                account_id=account_id,
                text_id=plan.text.id,
                proxy_id=proxy.id if proxy else None,
                status="sent",
                detail=plan.think,
            )
            await store.bump_sent(account_id)
            if proxy:
                await store.mark_proxy(proxy.id, "ok")
            sends_on_proxy += 1
        except asyncio.CancelledError:
            await store.release_contact(contact.id)
            raise
        except FloodWaitError as e:
            await store.release_contact(contact.id)
            extra = int(getattr(e, "seconds", 0) or 0) + 8
            await store.pause_account(account_id, extra, f"FloodWait {extra}с")
            await store.add_send(
                contact_id=contact.id,
                account_id=account_id,
                text_id=plan.text.id,
                proxy_id=proxy.id if proxy else None,
                status="wait",
                detail=f"FloodWait {extra}с",
            )
            await sink.emit(
                f"{escape(acc.label)} floodwait {extra}с — этот аккаунт отдыхает",
                level="warn",
                notify=True,
            )
            continue
        except PeerFloodError:
            await store.release_contact(contact.id)
            await store.pause_account(account_id, 3600, "PeerFlood")
            await sink.emit(
                f"{escape(acc.label)} PeerFlood — пауза 60 мин",
                level="warn",
                notify=True,
            )
            continue
        except AuthKeyUnregisteredError:
            await store.release_contact(contact.id)
            await store.update_account(
                account_id, status="error", last_error="Session умерла", assigned=0
            )
            await sink.emit(
                f"{escape(acc.label)} session невалидна — снял с рассылки",
                level="error",
                notify=True,
            )
            return
        except SKIP_ERRORS as e:
            msg = _err_text(e)
            await store.finish_contact(
                contact.id,
                "skip",
                account_id=account_id,
                text_id=plan.text.id,
                error=msg,
            )
            await store.add_send(
                contact_id=contact.id,
                account_id=account_id,
                text_id=plan.text.id,
                proxy_id=proxy.id if proxy else None,
                status="skip",
                detail=msg,
            )
        except Exception as e:
            msg = _err_text(e)
            low = msg.lower()
            if any(m in low for m in SKIP_MSG_MARKERS):
                await store.finish_contact(
                    contact.id,
                    "skip",
                    account_id=account_id,
                    text_id=plan.text.id,
                    error=msg,
                )
                await store.add_send(
                    contact_id=contact.id,
                    account_id=account_id,
                    text_id=plan.text.id,
                    proxy_id=proxy.id if proxy else None,
                    status="skip",
                    detail=msg,
                )
            else:
                proxy_fail = any(
                    w in low
                    for w in ("proxy", "timeout", "network", "connection", "socks", "connect")
                )
                if proxy_fail and proxy:
                    await store.mark_proxy(proxy.id, "error", msg)
                    await store.release_contact(contact.id)
                    proxy = None
                    sends_on_proxy = rotate_every
                    await sink.emit(
                        f"{escape(acc.label)} прокси сдох, беру следующий: {escape(msg)}",
                        level="warn",
                    )
                    continue
                await store.finish_contact(
                    contact.id,
                    "error",
                    account_id=account_id,
                    text_id=plan.text.id,
                    error=msg,
                )
                await store.add_send(
                    contact_id=contact.id,
                    account_id=account_id,
                    text_id=plan.text.id,
                    proxy_id=proxy.id if proxy else None,
                    status="error",
                    detail=msg,
                )
                await store.update_account(account_id, last_error=msg)

        lo, hi = _account_delays(acc, settings)
        if await _sleep_cancel(between_messages(lo, hi)):
            return

    await store.update_account(account_id, status="idle")


async def run_outreach(store: Store, bot, chat_id: int | None) -> None:
    await store.release_stuck_sending()
    job = await store.create_job("outreach", None)
    sink = LogSink(store, job.id, bot, chat_id)
    settings = await store.outreach_settings()
    counts = await store.counts()
    await sink.emit(
        f"старт: база {counts.pending} pending, аккаунты {counts.assigned}, "
        f"тексты {counts.texts}, прокси {counts.proxies}",
        notify=True,
    )

    workers: dict[int, asyncio.Task] = {}
    idle_exited: set[int] = set()

    async def ensure_workers(cfg: OutreachSettings, pending: int) -> None:
        for acc in await store.list_accounts():
            if not acc.telethon_session or not acc.assigned:
                continue
            task = workers.get(acc.id)
            alive = task is not None and not task.done()
            if alive:
                continue
            # Don't respawn workers that finished cleanly when queue is empty
            # (non-continuous) or when they already exited idle this cycle.
            if not cfg.continuous and pending <= 0:
                continue
            if acc.id in idle_exited and pending <= 0 and not cfg.continuous:
                continue
            if task is not None and task.done() and pending <= 0 and not cfg.continuous:
                idle_exited.add(acc.id)
                continue

            async def _wrap(aid: int = acc.id) -> None:
                try:
                    await _account_worker(store, aid, sink)
                finally:
                    idle_exited.add(aid)

            idle_exited.discard(acc.id)
            workers[acc.id] = asyncio.create_task(_wrap(), name=f"acc:{acc.id}")

    status = "done"
    report = ""
    try:
        while not runtime.cancelled("outreach", 0):
            settings = await store.outreach_settings()
            counts = await store.counts()
            await ensure_workers(settings, counts.pending)
            live = [t for t in workers.values() if not t.done()]

            if settings.continuous:
                await asyncio.sleep(2.0)
                continue

            if counts.pending == 0 and not live:
                break
            # pending exists but all workers idle-exited → respawn next loop
            if counts.pending > 0:
                for aid in list(idle_exited):
                    idle_exited.discard(aid)
            await asyncio.sleep(1.5)

        if runtime.cancelled("outreach", 0):
            status = "stopped"
        elif not settings.continuous:
            status = "done"
    except asyncio.CancelledError:
        status = "stopped"
        raise
    except Exception as e:
        status = "error"
        report = _err_text(e)
        log.exception("outreach failed")
    finally:
        runtime.request_cancel("outreach", 0)
        for task in workers.values():
            if not task.done():
                task.cancel()
        if workers:
            await asyncio.gather(*workers.values(), return_exceptions=True)
        for acc in await store.list_accounts():
            if acc.status in {"running", "paused"}:
                await store.update_account(acc.id, status="idle")
        await store.release_stuck_sending()
        counts = await store.counts()
        report = report or (
            f"sent {counts.sent} | pending {counts.pending} | "
            f"error {counts.errors} | skip {counts.skipped}"
        )
        await store.finish_job(job.id, status, report)
        await sink.emit(f"стоп ({status}): {report}", notify=True)
        if bot and chat_id:
            try:
                icon = "check" if status == "done" else "warn" if status == "error" else "down"
                await bot.send_message(
                    chat_id,
                    f"{pe(icon)} <b>Рассылка {status}</b>\n<code>{escape(report)}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
