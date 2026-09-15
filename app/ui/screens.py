from __future__ import annotations

from html import escape

from app.jobs.runtime import runtime
from app.models import (
    Account,
    BanContact,
    CollectRun,
    Contact,
    ContactBase,
    Counts,
    Proxy,
    SendRow,
    TextVariant,
)
from app.ui.emoji import pe
from app.utils.entities import entities_loads


def on_off(ok: bool) -> str:
    return f"{pe('check')} да" if ok else f"{pe('block')} нет"


def _step(ok: bool, title: str, detail: str) -> str:
    mark = pe("check") if ok else pe("pin")
    return f"{mark} <b>{title}</b> — {detail}"


async def home_html(store) -> str:
    counts: Counts = await store.counts()
    running = runtime.is_running("outreach", 0)
    bg = f"\n{pe('robot')} В фоне: <code>outreach</code>" if running else ""
    s1 = _step(counts.accounts > 0, "1. Аккаунты", f"{counts.accounts} / назначено {counts.assigned}")
    s2 = _step(True, "2. Прокси", f"{counts.proxies} (ротация на аккаунты)")
    s3 = _step(counts.contacts > 0, "3. База", f"{counts.contacts} · pending {counts.pending}")
    s4 = _step(counts.texts > 0, "4. Тексты", f"{counts.texts} вариант(ов)")
    s5 = _step(running, "5. Запуск", "идёт" if running else "ожидание")
    return (
        f"{pe('chart')} <b>Статистика</b>\n"
        f"Аккаунты: {counts.accounts} | Прокси: {counts.proxies} | "
        f"База: {counts.pending}/{counts.contacts} | "
        f"Sent: {counts.sent} | Фон: {int(running)}"
        f"{bg}\n\n"
        f"{pe('cube')} <b>Модуль outreach</b>\n"
        f"{s1}\n{s2}\n{s3}\n{s4}\n{s5}\n\n"
        f"Выберите действие:"
    )


def info_html() -> str:
    return (
        f"{pe('info')} <b>Outreach</b> 2.0\n"
        f"{pe('folder')} <b>Update:</b> 14.09.2026\n"
        f"{pe('at')} <b>Поддержка:</b> @arxixx\n\n"
        f"{pe('users')} Несколько баз: вкл/выкл, импорт txt/csv/xlsx/md/sql, экспорт.\n"
        f"{pe('search')} Сбор из чата: все / писавшие → база для рассылки.\n"
        f"{pe('mega')} ЛС: кому писали и кто отвечал — отдельные базы.\n"
        f"{pe('warn')} Банворды — в настройках модуля сбора.\n"
        f"{pe('user')} Аккаунты: session, рабочие часы, интервал, blocklist.\n"
        f"{pe('mega')} Офферы: random-ротация, premium emoji, фото.\n"
        f"{pe('robot')} 24/7 рассылка · один контакт = одно сообщение.\n"
        f"{pe('shield')} Прокси: авто-тип, ротация, проверка, привязка к аккаунту."
    )


def accounts_html(accounts: list[Account]) -> str:
    if not accounts:
        return (
            f"{pe('user')} <b>Аккаунты</b>\n\n"
            f"<i>Пока пусто. Нажмите «Добавить session» — загрузите .session.</i>"
        )
    lines = [f"{pe('user')} <b>Аккаунты</b> ({len(accounts)})\n"]
    for acc in accounts:
        live = pe("check") if acc.has_telethon else pe("block")
        asg = pe("check") if acc.assigned else pe("block")
        uname = f"@{acc.username}" if acc.username else escape(acc.label)
        lines.append(
            f"{live} <b>{escape(uname)}</b> <code>#{acc.id}</code> {asg} назначен\n"
            f"   статус: <code>{escape(acc.status)}</code> · sent {acc.sent_count}"
        )
    return "\n".join(lines)


def account_html(acc: Account, proxies: list[Proxy] | None = None) -> str:
    uname = f"@{acc.username}" if acc.username else "—"
    err = f"\n{pe('warn')} <b>Ошибка:</b> {escape(acc.last_error)}" if acc.last_error else ""
    pause = (
        f"\n{pe('clock')} пауза до <code>{escape(acc.pause_until)}</code>"
        if acc.pause_until
        else ""
    )
    wh = "24/7"
    if acc.work_start and acc.work_end:
        wh = f"{escape(acc.work_start)}–{escape(acc.work_end)}"
    dly = "глобальный"
    if acc.delay_min is not None and acc.delay_max is not None:
        dly = f"{acc.delay_min}–{acc.delay_max} сек"
    px = "нет"
    if proxies:
        px = ", ".join(escape(p.label) for p in proxies[:6])
        if len(proxies) > 6:
            px += f" +{len(proxies) - 6}"
    return (
        f"{pe('user')} <b>{escape(acc.label)}</b>\n\n"
        f"{pe('at')} {escape(uname)}\n"
        f"{pe('term')} tg_id: <code>{acc.user_id or '—'}</code>\n"
        f"{pe('bookmark')} статус: <code>{escape(acc.status)}</code>"
        f"{pause}\n"
        f"{pe('clock')} рабочие часы: <b>{wh}</b>\n"
        f"{pe('term')} интервал: <b>{dly}</b>\n"
        f"{pe('lock')} Telethon: {on_off(bool(acc.telethon_session))}\n"
        f"{pe('check') if acc.assigned else pe('block')} "
        f"{'назначен на рассылку' if acc.assigned else 'снят с рассылки'}\n"
        f"{pe('shield')} прокси: {px}\n"
        f"{pe('mega')} отправлено: <b>{acc.sent_count}</b>"
        f"{err}"
    )


def proxies_html(proxies: list[Proxy]) -> str:
    if not proxies:
        return (
            f"{pe('shield')} <b>Прокси</b>\n\n"
            f"<i>Пусто. Добавьте списком или файлом прямо здесь — тип определю сам.</i>"
        )
    ok = sum(1 for p in proxies if p.status == "ok")
    lines = [
        f"{pe('shield')} <b>Прокси</b> ({len(proxies)}, живых {ok})\n",
        f"{pe('robot')} Тип определяется сам: socks5 / socks4 / http / https. "
        f"После загрузки раскладываются по аккаунтам; если прокси больше — ротация.",
    ]
    for p in proxies[:12]:
        mark = pe("check") if p.status == "ok" else pe("warn")
        lines.append(f"{mark} <code>#{p.id}</code> {escape(p.label)}")
    if len(proxies) > 12:
        lines.append(f"… ещё {len(proxies) - 12}")
    return "\n".join(lines)


def proxy_html(proxy: Proxy, accounts: list[Account]) -> str:
    accs = ", ".join(escape(a.label) for a in accounts) or "—"
    err = f"\n{pe('warn')} {escape(proxy.last_error)}" if proxy.last_error else ""
    return (
        f"{pe('shield')} <b>Прокси #{proxy.id}</b>\n\n"
        f"<code>{escape(proxy.label)}</code>\n"
        f"{pe('cube')} тип: <b>{escape(proxy.scheme)}</b>\n"
        f"{pe('bookmark')} статус: <code>{escape(proxy.status)}</code>\n"
        f"{pe('user')} аккаунты: {accs}"
        f"{err}"
    )


def contacts_html(counts: Counts, kinds: dict[str, int], preview: list[Contact]) -> str:
    if counts.contacts == 0:
        return (
            f"{pe('users')} <b>База</b>\n\n"
            f"<i>Загрузите txt / csv / xlsx / md / json. Каждая строка — контакт.</i>\n"
            f"{pe('robot')} Сам пойму: @username, t.me/…, телефон, числовой ID."
        )
    kind_line = " · ".join(
        f"{k}: {v}" for k, v in sorted(kinds.items()) if v
    ) or "—"
    lines = [
        f"{pe('users')} <b>База</b> {counts.contacts}",
        f"{pe('inbox')} pending {counts.pending} | sent {counts.sent} | "
        f"error {counts.errors} | skip {counts.skipped}",
        f"{pe('search')} типы: {escape(kind_line)}\n",
    ]
    for c in preview:
        mark = {
            "pending": pe("pin"),
            "sent": pe("check"),
            "error": pe("warn"),
            "skip": pe("block"),
            "sending": pe("clock"),
        }.get(c.status, pe("cube"))
        extra = f" <i>{escape(c.last_error[:40])}</i>" if c.last_error else ""
        lines.append(
            f"{mark} {escape(c.pretty)} <code>{escape(c.kind)}</code>{extra}"
        )
    return "\n".join(lines)[:3900]


def texts_html(items: list[TextVariant]) -> str:
    if not items:
        return (
            f"{pe('mega')} <b>Тексты</b>\n\n"
            f"<i>Пришлите сообщение — текст, premium emoji, оформление и фото сохранятся. "
            f"Можно несколько вариантов, пойдут по очереди.</i>"
        )
    lines = [f"{pe('mega')} <b>Тексты</b> ({len(items)})\n"]
    for item in items:
        ents = entities_loads(item.entities_json)
        emoji_n = sum(1 for e in ents if "emoji" in str(e.get("type")))
        preview = escape((item.text or "").replace("\n", " ")[:120] or "—")
        en = on_off(bool(item.enabled))
        title = escape(item.title or f"вариант #{item.id}")
        lines.append(
            f"{pe('pin')} <b>{title}</b> {en}\n"
            f"   {len(item.text or '')} симв. | premium: {emoji_n} | "
            f"фото: {on_off(bool(item.photo_path))}\n"
            f"   <i>{preview}</i>"
        )
    return "\n".join(lines)[:3900]


def text_html(item: TextVariant) -> str:
    ents = entities_loads(item.entities_json)
    emoji_n = sum(1 for e in ents if "emoji" in str(e.get("type")))
    preview = escape((item.text or "")[:500] or "—")
    return (
        f"{pe('mega')} <b>{escape(item.title or f'вариант #{item.id}')}</b>\n\n"
        f"{pe('pin')} {len(item.text or '')} симв. | premium: {emoji_n} | "
        f"фото: {on_off(bool(item.photo_path))}\n"
        f"{pe('check') if item.enabled else pe('block')} "
        f"{'включён' if item.enabled else 'выключен'}\n\n"
        f"{preview}"
    )


def run_html(counts: Counts, accounts: list[Account], settings) -> str:
    running = runtime.is_running("outreach", 0)
    state = "идёт" if running else "остановлена"
    ready = (
        counts.assigned > 0
        and counts.pending > 0
        and counts.texts > 0
        and any(a.has_telethon and a.assigned for a in accounts)
    )
    lines = [
        f"{pe('robot')} <b>Рассылка</b> — {state}",
        f"{pe('users')} база pending: <b>{counts.pending}</b> / {counts.contacts}",
        f"{pe('mega')} sent {counts.sent} · error {counts.errors} · skip {counts.skipped}",
        f"{pe('clock')} интервал в аккаунте: "
        f"<b>{settings.delay_min}–{settings.delay_max}</b> сек · "
        f"24/7: {on_off(settings.continuous)}",
        f"{pe('term')} печатает: {on_off(settings.typing)} · "
        f"варианты: <code>{escape(settings.variant_mode)}</code>",
        f"{pe('shield')} смена прокси каждые <b>{settings.rotate_proxy_every}</b> сообщ.",
        "",
        f"{pe('user')} Аккаунты (по умолчанию все назначены):",
    ]
    for acc in accounts:
        mark = pe("check") if acc.assigned else pe("block")
        live = pe("lock") if acc.has_telethon else pe("warn")
        lines.append(
            f"{mark} {live} {escape(acc.label)} · {escape(acc.status)} · sent {acc.sent_count}"
        )
    if not accounts:
        lines.append("<i>Нет аккаунтов</i>")
    if not ready and not running:
        lines.append(
            f"\n{pe('info')} Чтобы стартовать: session + база + хотя бы один текст."
        )
    return "\n".join(lines)


def settings_html(settings) -> str:
    between = "нет"
    if settings.between_delay_max > 0 or settings.between_delay_min > 0:
        between = f"{settings.between_delay_min}–{settings.between_delay_max} сек"
    return (
        f"{pe('hammer')} <b>Настройки</b>\n\n"
        f"{pe('clock')} интервал в аккаунте: <b>{settings.delay_min}–{settings.delay_max}</b> сек\n"
        f"{pe('term')} между аккаунтами: <b>{between}</b>\n"
        f"{pe('term')} эффект «печатает…»: {on_off(settings.typing)}\n"
        f"{pe('stack')} офферы: <code>{escape(settings.variant_mode)}</code> "
        f"(random — каждый раз новый)\n"
        f"{pe('shield')} ротация прокси: каждые <b>{settings.rotate_proxy_every}</b> сообщ.\n"
        f"{pe('robot')} режим 24/7: {on_off(settings.continuous)}"
    )


def bases_html(bases: list[ContactBase], stats: dict[int, dict[str, int]]) -> str:
    if not bases:
        return (
            f"{pe('users')} <b>Базы контактов</b>\n\n"
            f"<i>Нет баз. Создайте первую — txt/csv/xlsx/md/sql.</i>"
        )
    lines = [f"{pe('users')} <b>Базы</b> ({len(bases)})\n"]
    for base in bases:
        st = stats.get(base.id, {})
        mark = pe("check") if base.enabled else pe("block")
        lines.append(
            f"{mark} <b>{escape(base.name)}</b> <code>#{base.id}</code>\n"
            f"   pending {st.get('pending', 0)} / {st.get('total', 0)} · sent {st.get('sent', 0)}"
        )
    return "\n".join(lines)


def base_html(base: ContactBase, stats: dict[str, int], preview: list[Contact]) -> str:
    mark = pe("check") if base.enabled else pe("block")
    lines = [
        f"{pe('users')} <b>{escape(base.name)}</b> {mark}\n",
        f"pending <b>{stats.get('pending', 0)}</b> / {stats.get('total', 0)} · "
        f"sent {stats.get('sent', 0)}\n",
    ]
    for c in preview:
        lines.append(f"{pe('pin')} {escape(c.pretty)} <code>{escape(c.status)}</code>")
    if not preview:
        lines.append("<i>Контактов пока нет — загрузите файл.</i>")
    return "\n".join(lines)[:3900]


def collect_html(accounts: list[Account] | None = None, running: bool = False) -> str:
    live = [a for a in (accounts or []) if a.has_telethon]
    bg = f"\n{pe('robot')} <b>Сбор идёт</b> — нажмите Стоп, чтобы сохранить уже собранное.\n" if running else "\n"
    return (
        f"{pe('search')} <b>Сбор базы для рассылки</b>{bg}\n"
        f"{pe('users')} <b>Все участники</b> — все из чата.\n"
        f"{pe('term')} <b>Писавшие</b> — только кто писал.\n"
        f"{pe('mega')} <b>Кому писали / Кто отвечал</b> — отдельные базы из ЛС.\n"
        f"{pe('check')} <b>Итоговая база</b> — без банвордов, «не пишем», "
        f"«кому писали», sent и дублей.\n"
        f"{pe('chart')} <b>История сбора</b> — бот и API, скачать txt/csv/xlsx.\n\n"
        f"{pe('robot')} Аккаунтов: <b>{len(live)}</b>\n"
        f"{pe('pin')} Приватный чат: id <code>-100…</code> работает, "
        f"если аккаунт уже состоит в чате (диалоги подгружаются)."
    )


def banwords_html(words: list[str], banned: list[BanContact]) -> str:
    lines = [
        f"{pe('hammer')} <b>Настройки сбора</b>\n\n"
        f"{pe('warn')} <b>Банворды</b> ({len(words)})\n"
        f"Если в сообщениях пользователя есть эти слова — "
        f"он не попадает в базу для рассылки, а уходит в банбазу.\n",
        ", ".join(escape(w) for w in words[:40]) or "<i>пусто — добавьте слова</i>",
        f"\n\n{pe('block')} <b>Банбаза</b> ({len(banned)})\n",
    ]
    for item in banned[:15]:
        lines.append(f"{pe('pin')} {escape(item.pretty)} — <i>{escape(item.reason[:40])}</i>")
    if not banned:
        lines.append("<i>пока пусто</i>")
    return "\n".join(lines)[:3900]


def collect_history_html(runs: list[CollectRun], page: int = 0) -> str:
    lines = [
        f"{pe('chart')} <b>История сбора</b>",
        f"Бот и API · стр. {page + 1}\n",
    ]
    if not runs:
        lines.append("<i>Пока пусто. Сборы из бота и POST /v1/collect/* появятся здесь.</i>")
        return "\n".join(lines)
    for run in runs:
        src = "API" if run.source == "api" else "бот"
        mark = pe("down") if run.stopped else pe("check")
        name = escape(run.base_name or run.title or run.mode or "—")
        when = escape((run.created_at or "")[:16].replace("T", " "))
        lines.append(
            f"{mark} <b>#{run.id}</b> [{escape(src)}] {name}\n"
            f"   {escape(run.kind)}/{escape(run.mode or '—')} · "
            f"+{run.added} · бан {run.banned} · {when}"
        )
    return "\n".join(lines)[:3900]


def collect_run_html(run: CollectRun) -> str:
    src = "API" if run.source == "api" else "бот"
    stop = " да" if run.stopped else " нет"
    return (
        f"{pe('folder')} <b>Сбор #{run.id}</b>\n\n"
        f"Источник: <b>{escape(src)}</b>\n"
        f"Тип: <code>{escape(run.kind)}</code> / <code>{escape(run.mode or '—')}</code>\n"
        f"Цель: <code>{escape(run.target or '—')}</code>\n"
        f"Название: <b>{escape(run.title or '—')}</b>\n"
        f"База: <b>{escape(run.base_name or '—')}</b> "
        f"<code>#{run.base_id or '—'}</code>\n"
        f"Аккаунт: <b>{escape(run.account_label or '—')}</b>\n"
        f"Добавлено: <b>{run.added}</b> · банбаза: <b>{run.banned}</b>\n"
        f"Остановка: <b>{stop}</b>\n"
        f"Когда: <code>{escape(run.created_at or '')}</code>\n"
        f"{pe('pin')} {escape((run.notes or '')[:300])}"
    )


def history_html(jobs, sends: list[SendRow]) -> str:
    lines = [f"{pe('chart')} <b>История</b>\n"]
    if jobs:
        lines.append(f"{pe('folder')} <b>Задачи</b>")
        for job in jobs[:8]:
            mark = (
                pe("check")
                if job.status == "done"
                else pe("warn")
                if job.status == "error"
                else pe("clock")
            )
            snippet = escape((job.report or "").replace("\n", " ")[:80])
            lines.append(
                f"{mark} #{job.id} <b>{escape(job.kind)}</b> "
                f"<code>{escape(job.status)}</code> {snippet}"
            )
        lines.append("")
    if not sends:
        lines.append("<i>Отправок пока нет.</i>")
        return "\n".join(lines)[:3900]
    lines.append(f"{pe('inbox')} <b>Последние отправки</b>")
    for row in sends:
        mark = {
            "sent": pe("check"),
            "skip": pe("block"),
            "error": pe("warn"),
            "wait": pe("clock"),
        }.get(row.status, pe("cube"))
        who = escape(row.contact_pretty or "—")
        acc = escape(row.account_label or "—")
        detail = escape((row.detail or "").replace("\n", " ")[:70])
        lines.append(f"{mark} {who} ← {acc}\n   <code>{escape(row.status)}</code> {detail}")
    return "\n".join(lines)[:3900]


def prompt_html(title: str, body: str, icon: str = "inbox") -> str:
    return f"{pe(icon)} <b>{title}</b>\n\n{body}"
