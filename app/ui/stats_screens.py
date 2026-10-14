"""HTML-экраны статистики и ответов для бота."""

from __future__ import annotations

from html import escape
from typing import Any

from app.analytics import fmt_duration
from app.models import Reply
from app.ui.emoji import pe

PERIODS: list[tuple[int | None, str]] = [(1, "24 ч"), (7, "7 дн"), (30, "30 дн"), (None, "Всё время")]


def period_label(idx: int) -> str:
    return PERIODS[idx % len(PERIODS)][1]


def period_days(idx: int) -> int | None:
    return PERIODS[idx % len(PERIODS)][0]


def bar(pct: float | None, width: int = 10) -> str:
    n = round((pct or 0) / 100 * width)
    return "█" * n + "░" * (width - n)


def _join(lines: list[str], limit: int = 3800) -> str:
    out: list[str] = []
    size = 0
    for line in lines:
        extra = len(line) + 1
        if size + extra > limit and out:
            out.append("…")
            break
        out.append(line)
        size += extra
    return "\n".join(out)


def _rate(x: dict[str, Any]) -> str:
    lo, hi = x["reply_rate_ci"]
    ci = f" [{lo:g}–{hi:g}]" if x["sent"] >= 10 else ""
    return f"{x['reply_rate']:g}%{ci}"


def overview_html(report: dict[str, Any], label: str) -> str:
    ov = report["overview"]
    lat = report["latency"]
    mine = report["our_response"]
    bl = report["backlog"]
    lines = [f"{pe('chart')} <b>Статистика · {escape(label)}</b>", ""]
    if not ov["attempts"] and not ov["reply_messages_received"]:
        lines.append("<i>За период пока нет данных.</i>")
        return "\n".join(lines)
    lines += [
        f"{pe('check')} Отправлено: <b>{ov['sent']}</b> "
        f"(доставка {ov['delivery_rate']:g}%) · ошибок {ov['errors']} · пропусков {ov['skipped']}",
        f"{pe('inbox')} Ответили: <b>{ov['responders']}</b> из {ov['sent']} — "
        f"<b>{_rate(ov)}</b>",
        f"Сообщений-ответов: {ov['reply_messages']} · редиректов (со ссылкой, "
        f"не засчитаны): {ov['redirect_contacts']}",
        f"Мы ответили: <b>{ov['answered']}</b> из {ov['responders']} · "
        f"диалог продолжили: {ov['continued']}",
    ]
    if bl["unanswered"]:
        lines.append(
            f"{pe('warn')} Ждут вашего ответа: <b>{bl['unanswered']}</b> "
            f"(старейший — {fmt_duration(bl['oldest_age_sec'])})"
        )

    lines += ["", f"{pe('stack')} <b>Воронка</b>"]
    top = report["funnel"][1]["count"] or report["funnel"][0]["count"] or 1
    for step in report["funnel"]:
        pct = round(step["count"] / top * 100, 1) if top else 0
        lines.append(f"<code>{bar(pct)}</code> {escape(step['stage'])}: {step['count']}")

    if lat["n"]:
        lines += [
            "",
            f"{pe('clock')} <b>Как быстро отвечают</b> (n={lat['n']})",
            f"медиана {fmt_duration(lat['median'])} · среднее {fmt_duration(lat['avg'])} · "
            f"p90 {fmt_duration(lat['p90'])}",
        ]
        for b in lat["buckets"]:
            if b["count"]:
                lines.append(f"<code>{bar(b['pct'])}</code> {escape(b['label'])} — {b['pct']:g}%")
    if mine["n"]:
        lines += [
            "",
            f"{pe('user')} Ваша реакция: медиана {fmt_duration(mine['median'])}, "
            f"p90 {fmt_duration(mine['p90'])}",
        ]
    if report["insights"]:
        lines += ["", f"{pe('star')} <b>Выводы</b>"]
        lines += [f"• {escape(t)}" for t in report["insights"]]
    return _join(lines)


def breakdown_html(
    title: str,
    items: list[dict[str, Any]],
    label: str,
    icon: str = "stack",
    *,
    max_rows: int = 14,
    hint: bool = True,
) -> str:
    lines = [f"{pe(icon)} <b>{escape(title)} · {escape(label)}</b>", ""]
    items = [x for x in items if x["attempts"] or x["sent"] or x["waits"]]
    if not items:
        lines.append("<i>Нет данных.</i>")
        return "\n".join(lines)
    for x in items[:max_rows]:
        err = f" · ош {x['errors']}" if x["errors"] else ""
        red = f" · ред {x['redirect_contacts']}" if x["redirect_contacts"] else ""
        lines.append(
            f"<b>{escape(str(x['label']))}</b>\n"
            f"<code>{bar(x['reply_rate'] * 2 if x['reply_rate'] < 50 else 100)}</code> "
            f"{_rate(x)} · {x['responders']}/{x['sent']}{err}{red}"
        )
    if len(items) > max_rows:
        lines.append(f"… и ещё {len(items) - max_rows}")
    if hint:
        lines += ["", "<i>Бар ×2: полный = 50%+. [a–b] — 95% интервал. ред — редиректы.</i>"]
    return _join(lines)


def compare_html(report: dict[str, Any], label: str, which: str) -> str:
    d = report["dims"]
    if which == "campaign":
        return (
            breakdown_html("Кампании", d["campaign"], label, "folder", max_rows=6, hint=False)
            + "\n\n"
            + breakdown_html("Базы", d["base"], label, "users", max_rows=6)
        )
    raise ValueError(which)


def time_html(report: dict[str, Any], label: str) -> str:
    lines = [f"{pe('clock')} <b>Время · {escape(label)}</b>", ""]
    hours = [h for h in report["dims"]["hour"] if h["sent"]]
    if not hours:
        return "\n".join(lines + ["<i>Нет данных.</i>"])
    lines.append("<b>Час отправки → % ответов</b>")
    for h in hours:
        lines.append(
            f"<code>{h['label']} {bar(h['reply_rate'] * 2 if h['reply_rate'] < 50 else 100, 8)}</code>"
            f" {h['reply_rate']:g}% ({h['responders']}/{h['sent']})"
        )
    lines += ["", "<b>День недели</b>"]
    for w in report["dims"]["weekday"]:
        if w["sent"]:
            lines.append(f"{escape(w['label'])}: {w['reply_rate']:g}% ({w['responders']}/{w['sent']})")
    peak = [h for h in report["reply_hours"] if h["replies"]]
    if peak:
        top = sorted(peak, key=lambda x: -x["replies"])[:3]
        lines += ["", "<b>Когда пишут ответы</b>: " + ", ".join(f"{p['label']} ({p['replies']})" for p in top)]
    daily = report["daily"][-7:]
    if daily:
        lines += ["", "<b>Последние дни</b> (отпр / ответов получено / редиректов)"]
        for d in daily:
            lines.append(
                f"{d['date'][5:]}: {d['sent']} / {d['replies_received']} / {d['redirects_received']}"
            )
    return _join(lines)


def errors_html(report: dict[str, Any], label: str) -> str:
    lines = [f"{pe('warn')} <b>Ошибки · {escape(label)}</b>", ""]
    if not report["errors"]:
        lines.append("<i>Ошибок нет.</i>")
        return "\n".join(lines)
    for e in report["errors"][:15]:
        lines.append(f"<code>{escape(e['status'])}</code> ×{e['count']} — {escape(e['reason'])}")
    return _join(lines)


# ------------------------------------------------------------------ replies


def _clip(text: str, n: int = 700) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def reply_body(reply: Reply) -> str:
    body = reply.text or (f"[{reply.media}]" if reply.media else "[пусто]")
    if reply.text and reply.media:
        body += f" [{reply.media}]"
    return body


def reply_notification_html(reply: Reply) -> str:
    meta = [f"аккаунт {escape(reply.account_label or '—')}"]
    if reply.campaign_name:
        meta.append(f"кампания {escape(reply.campaign_name)}")
    if reply.text_title:
        meta.append(f"оффер «{escape(reply.text_title)}»")
    name = escape(reply.who)
    if reply.from_name and reply.from_username:
        name += f" ({escape(reply.from_name)})"
    return (
        f"{pe('inbox')} <b>{name}</b> ответил(а):\n"
        f"<blockquote>{escape(_clip(reply_body(reply)))}</blockquote>\n"
        f"<i>{' · '.join(meta)}</i>"
    )


def replies_list_html(replies: list[Reply], total: int, page: int, pages: int) -> str:
    lines = [f"{pe('inbox')} <b>Ответы без реакции</b> · {total}", f"стр. {page + 1}/{pages}", ""]
    if not replies:
        lines.append("<i>Все ответы обработаны.</i>")
        return "\n".join(lines)
    for r in replies:
        when = escape((r.msg_date or "")[5:16].replace("T", " "))
        lines.append(
            f"<b>#{r.id}</b> {escape(r.who)} · {when}\n   «{escape(_clip(reply_body(r), 90))}»"
        )
    return _join(lines)


def reply_detail_html(reply: Reply, thread: list[dict[str, Any]]) -> str:
    lines = [reply_notification_html(reply), ""]
    if len(thread) > 1:
        lines.append("<b>Диалог</b>")
        for m in thread:
            who = "вы" if m["dir"] == "out" else escape(reply.who)
            body = m["text"] or (f"[{m['media']}]" if m.get("media") else "")
            lines.append(f"<b>{who}:</b> {escape(_clip(body, 200))}")
    state = {"new": "ждёт ответа", "answered": "отвечено", "ignored": "пропущено"}.get(
        reply.status, reply.status
    )
    lines.append(f"\nСтатус: <b>{state}</b>")
    return _join(lines)
