"""
Аналитика рассылки: отправки, ответы, редиректы, скорость реакции, срезы по
офферам / аккаунтам / кампаниям / базам / времени.

Правила учёта:
  * «Ответ» — входящее без ссылок. Сообщения со ссылками (valid=0) — редиректы,
    в ответы не входят и показываются отдельно.
  * Ответы считаются по когорте: берём отправки за период и смотрим, ответил ли
    адресат (когда бы ни ответил). Так конверсия честная для любого среза.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import aiosqlite

from app.config import get_settings

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
LATENCY_BUCKETS: list[tuple[str, float]] = [
    ("< 5 мин", 5 * 60),
    ("5–30 мин", 30 * 60),
    ("30 мин – 2 ч", 2 * 3600),
    ("2–6 ч", 6 * 3600),
    ("6–24 ч", 24 * 3600),
    ("1–3 дня", 3 * 86400),
    ("> 3 дней", math.inf),
]
MIN_SAMPLE = 20  # меньше отправок — выводы по срезу считаем шумом


# ------------------------------------------------------------------ helpers


def _tz() -> ZoneInfo:
    try:
        return get_settings().tz
    except Exception:
        return ZoneInfo("UTC")


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% доверительный интервал доли (границы в процентах)."""
    if total <= 0:
        return 0.0, 0.0
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return round(max(0.0, centre - margin) * 100, 1), round(min(1.0, centre + margin) * 100, 1)


def _pct(num: int, den: int) -> float:
    return round(num / den * 100, 1) if den else 0.0


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _latency_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "avg": None, "median": None, "p90": None, "buckets": []}
    buckets = []
    prev = 0.0
    for label, upper in LATENCY_BUCKETS:
        n = sum(1 for v in values if prev <= v < upper)
        buckets.append({"label": label, "count": n, "pct": _pct(n, len(values))})
        prev = upper
    return {
        "n": len(values),
        "avg": round(statistics.fmean(values), 1),
        "median": round(statistics.median(values), 1),
        "p90": round(_percentile(values, 0.9) or 0, 1),
        "buckets": buckets,
    }


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s} с"
    if s < 3600:
        return f"{s // 60} мин"
    if s < 86400:
        h, m = divmod(s // 60, 60)
        return f"{h} ч {m} мин" if m else f"{h} ч"
    d, h = divmod(s // 3600, 24)
    return f"{d} д {h} ч" if h else f"{d} д"


def period_bounds(
    days: int | None = None,
    since: str | None = None,
    until: str | None = None,
) -> tuple[str | None, str | None]:
    """days=1 — последние 24 часа; days=None и пусто — всё время."""
    if days:
        start = datetime.now(timezone.utc) - timedelta(days=days)
        return start.isoformat(timespec="seconds"), until
    return since, until


# ------------------------------------------------------------------ loading

_SENDS_SQL = """
SELECT s.id, s.contact_id, s.account_id, s.text_id, s.proxy_id, s.status, s.detail,
       s.created_at, s.campaign_id, s.campaign_name,
       c.base_id AS base_id, c.kind AS ckind,
       (SELECT MIN(r.msg_date) FROM replies r WHERE r.send_id=s.id AND r.valid=1) AS first_reply_at,
       (SELECT MAX(r.msg_date) FROM replies r WHERE r.send_id=s.id AND r.valid=1) AS last_reply_at,
       (SELECT COUNT(*) FROM replies r WHERE r.send_id=s.id AND r.valid=1) AS reply_msgs,
       (SELECT COUNT(*) FROM replies r WHERE r.send_id=s.id AND r.valid=0) AS link_msgs,
       (SELECT MIN(a.created_at) FROM reply_answers a
          JOIN replies r ON r.id=a.reply_id WHERE r.send_id=s.id) AS first_answer_at
FROM sends s LEFT JOIN contacts c ON c.id=s.contact_id
"""

_REPLIES_SQL = """
SELECT r.id, r.account_id, r.send_id, r.text_id, r.campaign_id, r.campaign_name, r.peer_id,
       r.valid, r.status, r.msg_date, r.text, r.media, r.from_username, r.from_name,
       (SELECT MIN(a.created_at) FROM reply_answers a
          WHERE a.account_id IS r.account_id AND a.peer_id=r.peer_id
            AND a.created_at>=r.msg_date) AS answer_at
FROM replies r
"""


def _where(
    col_date: str,
    since: str | None,
    until: str | None,
    campaign_id: int | None,
    account_id: int | None,
    prefix: str,
) -> tuple[str, list[Any]]:
    conds: list[str] = []
    args: list[Any] = []
    if since:
        conds.append(f"{prefix}.{col_date}>=?")
        args.append(since)
    if until:
        conds.append(f"{prefix}.{col_date}<?")
        args.append(until)
    if campaign_id is not None:
        conds.append(f"{prefix}.campaign_id=?")
        args.append(campaign_id)
    if account_id is not None:
        conds.append(f"{prefix}.account_id=?")
        args.append(account_id)
    return ("WHERE " + " AND ".join(conds) if conds else ""), args


async def _fetch(store, sql: str, args: list[Any]) -> list[dict[str, Any]]:
    async with store._connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, args)
        return [dict(r) for r in await cur.fetchall()]


# ------------------------------------------------------------------ aggregation


def _stat(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sent_rows = [r for r in rows if r["status"] == "sent"]
    n_sent = len(sent_rows)
    n_err = sum(1 for r in rows if r["status"] == "error")
    n_skip = sum(1 for r in rows if r["status"] == "skip")
    n_wait = sum(1 for r in rows if r["status"] == "wait")
    responders = [r for r in sent_rows if r["reply_msgs"] > 0]
    redirects = [r for r in sent_rows if r["reply_msgs"] == 0 and r["link_msgs"] > 0]
    answered = [r for r in responders if r["first_answer_at"]]
    lat: list[float] = []
    for r in responders:
        a, b = parse_ts(r["created_at"]), parse_ts(r["first_reply_at"])
        if a and b:
            lat.append(max(0.0, (b - a).total_seconds()))
    final = n_sent + n_err + n_skip
    lo, hi = wilson(len(responders), n_sent)
    return {
        "attempts": final,
        "sent": n_sent,
        "errors": n_err,
        "skipped": n_skip,
        "waits": n_wait,
        "delivery_rate": _pct(n_sent, final),
        "error_rate": _pct(n_err, final),
        "responders": len(responders),
        "reply_rate": _pct(len(responders), n_sent),
        "reply_rate_ci": [lo, hi],
        "reply_messages": sum(r["reply_msgs"] for r in sent_rows),
        "redirect_contacts": len(redirects),
        "answered": len(answered),
        "unanswered": len(responders) - len(answered),
        "avg_reply_sec": round(statistics.fmean(lat), 1) if lat else None,
        "median_reply_sec": round(statistics.median(lat), 1) if lat else None,
    }


def _group(
    rows: list[dict[str, Any]],
    keyfn: Callable[[dict[str, Any]], Any],
    label: Callable[[Any], str],
    *,
    sort_key: str = "sent",
) -> list[dict[str, Any]]:
    buckets: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        buckets[keyfn(r)].append(r)
    out = []
    for key, items in buckets.items():
        item = _stat(items)
        item["key"] = key
        item["label"] = label(key)
        out.append(item)
    out.sort(key=lambda x: (-x[sort_key], str(x["label"])))
    return out


# ------------------------------------------------------------------ report


async def build_report(
    store,
    *,
    days: int | None = None,
    since: str | None = None,
    until: str | None = None,
    campaign_id: int | None = None,
    account_id: int | None = None,
) -> dict[str, Any]:
    since, until = period_bounds(days, since, until)
    tz = _tz()

    where, args = _where("created_at", since, until, campaign_id, account_id, "s")
    rows = await _fetch(store, _SENDS_SQL + where, args)
    where, args = _where("msg_date", since, until, campaign_id, account_id, "r")
    reply_rows = await _fetch(store, _REPLIES_SQL + where, args)

    accounts = {a.id: a.label or a.display for a in await store.list_accounts()}
    texts = {}
    for t in await store.list_texts():
        texts[t.id] = (t.title or (t.text or "").strip().replace("\n", " ")[:32] or f"#{t.id}")
    bases = {b.id: b.name for b in await store.list_bases()}
    camps = {c.id: c.name for c in await store.list_campaigns()}
    proxies = {p.id: p.label for p in await store.list_proxies()}

    def lab(mapping: dict[int, str], prefix: str) -> Callable[[Any], str]:
        return lambda k: mapping.get(k, f"{prefix} #{k}") if k is not None else "—"

    def camp_label(row_key: Any) -> str:
        return camps.get(row_key, f"Кампания #{row_key}") if row_key is not None else "Основной"

    def local(row: dict[str, Any]) -> datetime:
        dt = parse_ts(row["created_at"]) or datetime.now(timezone.utc)
        return dt.astimezone(tz)

    sent_rows = [r for r in rows if r["status"] == "sent"]
    overview = _stat(rows)

    valid_replies = [r for r in reply_rows if r["valid"]]
    link_replies = [r for r in reply_rows if not r["valid"]]
    people_in = {(r["account_id"], r["peer_id"]) for r in valid_replies}
    answer_lat: list[float] = []
    for r in valid_replies:
        a, b = parse_ts(r["msg_date"]), parse_ts(r["answer_at"])
        if a and b:
            answer_lat.append(max(0.0, (b - a).total_seconds()))
    overview.update(
        {
            "contacts_reached": len({r["contact_id"] for r in sent_rows if r["contact_id"]}),
            "reply_messages_received": len(valid_replies),
            "people_replied_in_period": len(people_in),
            "redirect_messages": len(link_replies),
            "redirect_share": _pct(
                len({(r["account_id"], r["peer_id"]) for r in link_replies}),
                len(people_in)
                + len({(r["account_id"], r["peer_id"]) for r in link_replies} - people_in),
            ),
            "continued": sum(
                1
                for r in sent_rows
                if r["first_answer_at"]
                and r["last_reply_at"]
                and r["last_reply_at"] > r["first_answer_at"]
            ),
        }
    )

    lat = []
    for r in sent_rows:
        a, b = parse_ts(r["created_at"]), parse_ts(r["first_reply_at"])
        if a and b and r["reply_msgs"] > 0:
            lat.append(max(0.0, (b - a).total_seconds()))

    funnel = [
        {"stage": "Попыток отправки", "count": overview["attempts"]},
        {"stage": "Доставлено", "count": overview["sent"]},
        {"stage": "Ответили", "count": overview["responders"]},
        {"stage": "Мы ответили", "count": overview["answered"]},
        {"stage": "Диалог продолжился", "count": overview["continued"]},
    ]
    for i, step in enumerate(funnel):
        prev = funnel[i - 1]["count"] if i else None
        step["pct_of_prev"] = _pct(step["count"], prev) if prev else None
        step["pct_of_sent"] = _pct(step["count"], overview["sent"]) if overview["sent"] else None

    dims = {
        "account": _group(rows, lambda r: r["account_id"], lab(accounts, "Аккаунт")),
        "text": _group(rows, lambda r: r["text_id"], lab(texts, "Оффер")),
        "campaign": _group(
            rows,
            lambda r: r["campaign_id"],
            lambda k: camp_label(k),
        ),
        "base": _group(rows, lambda r: r["base_id"], lab(bases, "База")),
        "kind": _group(
            rows,
            lambda r: r["ckind"] or "unknown",
            lambda k: {"username": "@username", "phone": "телефон", "user_id": "user id"}.get(
                k, str(k)
            ),
        ),
        "proxy": _group(rows, lambda r: r["proxy_id"], lab(proxies, "Прокси")),
    }
    hours = _group(
        rows, lambda r: local(r).hour, lambda k: f"{k:02d}:00", sort_key="key"
    )
    for h in hours:
        h["label"] = f"{h['key']:02d}:00"
    hours.sort(key=lambda x: x["key"])
    weekdays = _group(rows, lambda r: local(r).weekday(), lambda k: WEEKDAYS[k], sort_key="key")
    weekdays.sort(key=lambda x: x["key"])
    dims["hour"] = hours
    dims["weekday"] = weekdays

    # динамика по дням (локальная дата)
    daily_map: dict[date, dict[str, Any]] = {}
    for key, items in _group_raw(rows, lambda r: local(r).date()).items():
        st = _stat(items)
        daily_map[key] = {
            "date": key.isoformat(),
            "sent": st["sent"],
            "errors": st["errors"],
            "responders": st["responders"],
            "reply_rate": st["reply_rate"],
            "replies_received": 0,
            "redirects_received": 0,
        }
    for r in reply_rows:
        dt = parse_ts(r["msg_date"])
        if not dt:
            continue
        d = dt.astimezone(tz).date()
        slot = daily_map.setdefault(
            d,
            {
                "date": d.isoformat(),
                "sent": 0,
                "errors": 0,
                "responders": 0,
                "reply_rate": 0.0,
                "replies_received": 0,
                "redirects_received": 0,
            },
        )
        slot["replies_received" if r["valid"] else "redirects_received"] += 1
    daily = [daily_map[k] for k in sorted(daily_map)][-366:]

    reply_hours = [0] * 24
    for r in valid_replies:
        dt = parse_ts(r["msg_date"])
        if dt:
            reply_hours[dt.astimezone(tz).hour] += 1

    # ошибки
    err_counter: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        if r["status"] in ("error", "skip", "wait"):
            err_counter[(r["status"], _normalize_error(r["detail"]))] += 1
    errors = [
        {"status": st, "reason": reason, "count": n}
        for (st, reason), n in sorted(err_counter.items(), key=lambda kv: -kv[1])[:20]
    ]

    backlog = await _backlog(store)

    report = {
        "period": {"since": since, "until": until, "days": days, "timezone": str(tz)},
        "filters": {"campaign_id": campaign_id, "account_id": account_id},
        "overview": overview,
        "latency": _latency_summary(lat),
        "our_response": _latency_summary(answer_lat),
        "funnel": funnel,
        "dims": dims,
        "daily": daily,
        "reply_hours": [{"hour": h, "label": f"{h:02d}:00", "replies": n} for h, n in enumerate(reply_hours)],
        "errors": errors,
        "backlog": backlog,
    }
    report["insights"] = build_insights(report)
    return report


def _group_raw(rows, keyfn) -> dict[Any, list[dict[str, Any]]]:
    out: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        out[keyfn(r)].append(r)
    return out


def _normalize_error(detail: str | None) -> str:
    text = (detail or "").strip()
    if ": " in text:  # "<кампания>: <причина>"
        text = text.split(": ", 1)[1]
    import re

    text = re.sub(r"\d+", "N", text)
    return text[:90] or "—"


async def _backlog(store) -> dict[str, Any]:
    rows = await _fetch(
        store,
        "SELECT msg_date FROM replies WHERE valid=1 AND status='new' ORDER BY msg_date",
        [],
    )
    oldest = parse_ts(rows[0]["msg_date"]) if rows else None
    age = (datetime.now(timezone.utc) - oldest).total_seconds() if oldest else None
    return {"unanswered": len(rows), "oldest_age_sec": round(age) if age is not None else None}


# ------------------------------------------------------------------ insights


def build_insights(report: dict[str, Any], min_n: int = MIN_SAMPLE) -> list[str]:
    out: list[str] = []
    ov = report["overview"]
    if not ov["sent"]:
        return ["За выбранный период нет отправок."]

    def ranked(dim: str) -> list[dict[str, Any]]:
        return [x for x in report["dims"][dim] if x["sent"] >= min_n]

    texts = ranked("text")
    if len(texts) >= 2:
        best = max(texts, key=lambda x: x["reply_rate_ci"][0])
        worst = min(texts, key=lambda x: x["reply_rate"])
        if best is not worst and best["reply_rate"] > worst["reply_rate"]:
            sig = "" if best["reply_rate_ci"][0] > worst["reply_rate_ci"][1] else " (разница пока в пределах погрешности)"
            out.append(
                f"Лучший оффер «{best['label']}»: {best['reply_rate']}% ответов "
                f"(n={best['sent']}) против {worst['reply_rate']}% у «{worst['label']}»{sig}."
            )
    elif not texts and report["dims"]["text"]:
        out.append(f"На каждый оффер пока меньше {min_n} отправок — сравнивать рано.")

    hours = [h for h in ranked("hour") if h["responders"] > 0]
    if len(hours) >= 3:
        best = max(hours, key=lambda x: x["reply_rate"])
        out.append(
            f"Лучше всего отвечают на сообщения, отправленные в {best['label']}: "
            f"{best['reply_rate']}% (n={best['sent']})."
        )
    rh = max(report["reply_hours"], key=lambda x: x["replies"])
    if rh["replies"] > 0:
        out.append(f"Пик входящих ответов — около {rh['label']} ({rh['replies']} сообщ.).")

    accs = ranked("account")
    for acc in accs:
        if acc["error_rate"] >= 30 and acc["attempts"] >= min_n:
            out.append(
                f"Аккаунт «{acc['label']}»: {acc['error_rate']}% ошибок из {acc['attempts']} — "
                "проверьте прокси/session."
            )
    if len(accs) >= 2:
        top = max(accs, key=lambda x: x["reply_rate"])
        out.append(f"Лучший аккаунт по ответам — «{top['label']}»: {top['reply_rate']}%.")

    if ov["redirect_contacts"] and ov["responders"] + ov["redirect_contacts"]:
        share = _pct(ov["redirect_contacts"], ov["responders"] + ov["redirect_contacts"])
        if share >= 25:
            out.append(
                f"{share}% «ответивших» прислали только ссылки (редиректы) — в ответы они не засчитаны."
            )

    bl = report["backlog"]
    if bl["unanswered"]:
        age = fmt_duration(bl["oldest_age_sec"])
        out.append(f"Без ответа от вас: {bl['unanswered']} (самый старый — {age}).")
    med = report["our_response"]["median"]
    if med is not None and med > 3600:
        out.append(f"Медианное время вашей реакции — {fmt_duration(med)}: быстрее ответ — выше шанс диалога.")
    if ov["responders"] and ov["answered"] < ov["responders"] * 0.5:
        out.append("Вы ответили меньше чем половине тех, кто написал — проверьте раздел «Ответы».")
    return out
