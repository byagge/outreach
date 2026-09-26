from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
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
from app.models import Account, OutreachSettings, TextVariant
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


@dataclass
class OutreachScope:
    """Область рассылки: основная или отдельная кампания."""

    runtime_kind: str = "outreach"  # outreach | campaign
    runtime_id: int = 0
    campaign_id: int | None = None
    campaign_name: str = "Основной"
    account_ids: list[int] | None = None  # None = назначенные (assigned)
    base_ids: list[int] | None = None  # None = mailing pool
    text_ids: list[int] | None = None  # None = все enabled
    mailing_only: bool = True

    @property
    def tag(self) -> str:
        return self.campaign_name or "Основной"

    @property
    def log_prefix(self) -> str:
        return f"[{escape(self.tag)}] "


def main_scope() -> OutreachScope:
    return OutreachScope(
        runtime_kind="outreach",
        runtime_id=0,
        campaign_id=None,
        campaign_name="Основной",
        mailing_only=True,
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


async def _sleep_cancel(seconds: float, scope: OutreachScope) -> bool:
    left = max(0.0, seconds)
    while left > 0:
        if runtime.cancelled(scope.runtime_kind, scope.runtime_id):
            return True
        step = min(1.0, left)
        await asyncio.sleep(step)
        left -= step
    return runtime.cancelled(scope.runtime_kind, scope.runtime_id)


async def _load_texts(store: Store, scope: OutreachScope) -> list[TextVariant]:
    if scope.text_ids is not None:
        texts = await store.list_texts_by_ids(scope.text_ids)
        return [t for t in texts if t.enabled and ((t.text or "").strip() or (t.photo_path or "").strip())]
    texts = await store.list_texts(enabled_only=True)
    return [t for t in texts if (t.text or "").strip() or (t.photo_path or "").strip()]


async def _account_worker(store: Store, account_id: int, sink: LogSink, scope: OutreachScope) -> None:
    proxy = None
    sends_on_proxy = 0
    tz = get_settings().tz
    prefix = scope.log_prefix

    while not runtime.cancelled(scope.runtime_kind, scope.runtime_id):
        settings = await store.outreach_settings()
        acc = await store.get_account(account_id)
        if not acc or not acc.telethon_session:
            return

        # основная: только assigned; кампания: список зафиксирован при старте
        if scope.account_ids is None and not acc.assigned:
            if await _sleep_cancel(2.5, scope):
                return
            continue

        if not in_work_hours(acc.work_start, acc.work_end, tz):
            await store.update_account(account_id, status="idle")
            if await _sleep_cancel(30, scope):
                return
            continue

        wait = _pause_left(acc)
        if wait > 0:
            await store.update_account(account_id, status="paused")
            if await _sleep_cancel(min(wait, 20), scope):
                return
            continue

        usable = await _load_texts(store, scope)
        if not usable:
            if await _sleep_cancel(3, scope):
                return
            continue

        contact = await store.claim_contact(
            base_ids=scope.base_ids,
            mailing_only=scope.mailing_only if scope.base_ids is None else False,
        )
        if not contact:
            await store.update_account(account_id, status="idle")
            if settings.continuous:
                if await _sleep_cancel(5, scope):
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
            await sink.emit(f"{prefix}{escape(_err_text(e))}", level="warn")
            if await _sleep_cancel(3, scope):
                return
            continue

        await sink.emit(f"{prefix}{escape(acc.label)}: {escape(plan.think)}")
        await store.update_account(account_id, status="running", last_error="")
        camp_kw = dict(campaign_id=scope.campaign_id, campaign_name=scope.campaign_name)

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
                detail=f"{scope.tag}: {plan.think}",
                **camp_kw,
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
                detail=f"{scope.tag}: FloodWait {extra}с",
                **camp_kw,
            )
            await sink.emit(
                f"{prefix}{escape(acc.label)} floodwait {extra}с — этот аккаунт отдыхает",
                level="warn",
                notify=True,
            )
            continue
        except PeerFloodError:
            await store.release_contact(contact.id)
            await store.pause_account(account_id, 3600, "PeerFlood")
            await sink.emit(
                f"{prefix}{escape(acc.label)} PeerFlood — пауза 60 мин",
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
                f"{prefix}{escape(acc.label)} session невалидна — снял с рассылки",
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
                detail=f"{scope.tag}: {msg}",
                **camp_kw,
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
                    detail=f"{scope.tag}: {msg}",
                    **camp_kw,
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
                        f"{prefix}{escape(acc.label)} прокси сдох, беру следующий: {escape(msg)}",
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
                    detail=f"{scope.tag}: {msg}",
                    **camp_kw,
                )
                await store.update_account(account_id, last_error=msg)

        lo, hi = _account_delays(acc, settings)
        if await _sleep_cancel(between_messages(lo, hi), scope):
            return

    await store.update_account(account_id, status="idle")


async def run_outreach(
    store: Store,
    bot,
    chat_id: int | None,
    scope: OutreachScope | None = None,
) -> None:
    scope = scope or main_scope()
    await store.release_stuck_sending()
    job = await store.create_job(
        scope.runtime_kind,
        None,
        campaign_id=scope.campaign_id,
        campaign_name=scope.campaign_name,
    )
    sink = LogSink(store, job.id, bot, chat_id)
    settings = await store.outreach_settings()
    pending = await store.count_pending(
        base_ids=scope.base_ids,
        mailing_only=scope.mailing_only if scope.base_ids is None else False,
    )
    texts = await _load_texts(store, scope)
    accounts = await _scope_accounts(store, scope)
    prefix = scope.log_prefix
    await sink.emit(
        f"{prefix}старт: pending {pending}, аккаунты {len(accounts)}, "
        f"офферы {len(texts)}, базы "
        f"{'mailing' if scope.base_ids is None else len(scope.base_ids or [])}",
        notify=True,
    )

    workers: dict[int, asyncio.Task] = {}
    idle_exited: set[int] = set()

    async def ensure_workers(cfg: OutreachSettings, pending_n: int) -> None:
        for acc in await _scope_accounts(store, scope):
            if not acc.telethon_session:
                continue
            if scope.account_ids is None and not acc.assigned:
                continue
            task = workers.get(acc.id)
            alive = task is not None and not task.done()
            if alive:
                continue
            if not cfg.continuous and pending_n <= 0:
                continue
            if acc.id in idle_exited and pending_n <= 0 and not cfg.continuous:
                continue
            if task is not None and task.done() and pending_n <= 0 and not cfg.continuous:
                idle_exited.add(acc.id)
                continue

            async def _wrap(aid: int = acc.id) -> None:
                try:
                    await _account_worker(store, aid, sink, scope)
                finally:
                    idle_exited.add(aid)

            idle_exited.discard(acc.id)
            workers[acc.id] = asyncio.create_task(
                _wrap(), name=f"{scope.runtime_kind}:{scope.runtime_id}:acc:{acc.id}"
            )

    status = "done"
    report = ""
    try:
        while not runtime.cancelled(scope.runtime_kind, scope.runtime_id):
            settings = await store.outreach_settings()
            pending_n = await store.count_pending(
                base_ids=scope.base_ids,
                mailing_only=scope.mailing_only if scope.base_ids is None else False,
            )
            await ensure_workers(settings, pending_n)
            live = [t for t in workers.values() if not t.done()]

            if settings.continuous:
                await asyncio.sleep(2.0)
                continue

            if pending_n == 0 and not live:
                break
            if pending_n > 0:
                for aid in list(idle_exited):
                    idle_exited.discard(aid)
            await asyncio.sleep(1.5)

        if runtime.cancelled(scope.runtime_kind, scope.runtime_id):
            status = "stopped"
        elif not settings.continuous:
            status = "done"
    except asyncio.CancelledError:
        status = "stopped"
        raise
    except Exception as e:
        status = "error"
        report = _err_text(e)
        log.exception("outreach failed (%s)", scope.tag)
    finally:
        runtime.request_cancel(scope.runtime_kind, scope.runtime_id)
        for task in workers.values():
            if not task.done():
                task.cancel()
        if workers:
            await asyncio.gather(*workers.values(), return_exceptions=True)
        for aid in list(workers.keys()):
            try:
                await store.update_account(aid, status="idle")
            except Exception:
                pass
        await store.release_stuck_sending()
        pending_n = await store.count_pending(
            base_ids=scope.base_ids,
            mailing_only=scope.mailing_only if scope.base_ids is None else False,
        )
        counts = await store.counts()
        report = report or (
            f"{scope.tag}: sent {counts.sent} | pending {pending_n} | "
            f"error {counts.errors} | skip {counts.skipped}"
        )
        await store.finish_job(job.id, status, report)
        await sink.emit(f"{prefix}стоп ({status}): {report}", notify=True)
        if bot and chat_id:
            try:
                icon = "check" if status == "done" else "warn" if status == "error" else "down"
                await bot.send_message(
                    chat_id,
                    f"{pe(icon)} <b>{escape(scope.tag)} — {status}</b>\n"
                    f"<code>{escape(report)}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass


async def _scope_accounts(store: Store, scope: OutreachScope) -> list[Account]:
    all_acc = await store.list_accounts()
    if scope.account_ids is None:
        return [a for a in all_acc if a.assigned and a.has_telethon]
    wanted = set(scope.account_ids)
    return [a for a in all_acc if a.id in wanted and a.has_telethon]


async def build_campaign_scope(store: Store, campaign_id: int) -> OutreachScope:
    camp = await store.get_campaign(campaign_id)
    if not camp:
        raise RuntimeError("Кампания не найдена")
    if camp.is_main:
        main = await store.get_main_campaign()
        return OutreachScope(
            runtime_kind="outreach",
            runtime_id=0,
            campaign_id=main.id,
            campaign_name=main.name or "Основной",
            mailing_only=True,
        )
    base_ids = await store.campaign_base_ids(campaign_id)
    account_ids = await store.campaign_account_ids(campaign_id)
    text_ids = await store.campaign_text_ids(campaign_id)
    return OutreachScope(
        runtime_kind="campaign",
        runtime_id=campaign_id,
        campaign_id=campaign_id,
        campaign_name=camp.name,
        account_ids=account_ids,
        base_ids=base_ids,
        text_ids=text_ids,
        mailing_only=False,
    )
