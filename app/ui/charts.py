"""PNG-диаграммы для отчётов outreach (бот и API).

Стиль как у marketing/table_image: Pillow, системные шрифты, без matplotlib.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

BG = (248, 250, 252)
PANEL = (255, 255, 255)
HEADER = (15, 23, 42)
MUTED = (100, 116, 139)
GRID = (226, 232, 240)
ACCENT = (8, 145, 178)
ACCENT_DIM = (165, 243, 252)
GOOD = (22, 163, 74)
WARN = (217, 119, 6)
BAD = (220, 38, 38)
TEXT = (30, 41, 59)
BAR_ALT = (14, 116, 144)

_FONT_DIRS = (
    Path(r"C:\Windows\Fonts"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/liberation"),
    Path("/usr/share/fonts/truetype/freefont"),
)
_REGULAR = ("segoeui.ttf", "arial.ttf", "tahoma.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf")
_BOLD = ("segoeuib.ttf", "arialbd.ttf", "tahomabd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf")

CHART_KINDS = (
    "dashboard",
    "funnel",
    "offers",
    "accounts",
    "campaigns",
    "timeline",
    "latency",
    "hours",
)


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    names = _BOLD if bold else _REGULAR
    for folder in _FONT_DIRS:
        for name in names:
            path = folder / name
            if path.exists():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _fit(text: str, max_chars: int) -> str:
    text = (text or "").replace("\n", " ").strip() or "—"
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _tw(font, text: str) -> float:
    if hasattr(font, "getlength"):
        return font.getlength(text)
    return len(text) * (font.size * 0.55 if hasattr(font, "size") else 7)


def _png(img) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _blank(w: int, h: int, title: str, note: str = "Нет данных за период") -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    draw.text((24, 20), _fit(title, 60), font=_font(18, True), fill=HEADER)
    draw.text((24, h // 2 - 8), note, font=_font(14), fill=MUTED)
    return _png(img)


def _header(draw, title: str, subtitle: str, width: int) -> int:
    title_f = _font(18, True)
    sub_f = _font(12)
    draw.text((24, 18), _fit(title, 70), font=title_f, fill=HEADER)
    draw.text((24, 44), _fit(subtitle, 95), font=sub_f, fill=MUTED)
    draw.line((24, 68, width - 24, 68), fill=GRID, width=1)
    return 82


# ------------------------------------------------------------------ primitives


def render_funnel_png(
    funnel: list[dict[str, Any]],
    *,
    title: str = "Воронка",
    subtitle: str = "",
) -> bytes:
    from PIL import Image, ImageDraw

    if not funnel or not any(s.get("count") for s in funnel):
        return _blank(720, 320, title)

    width, row_h, pad = 720, 42, 24
    height = pad * 2 + 80 + row_h * len(funnel) + 20
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    top = _header(draw, title, subtitle, width)
    max_n = max(int(s.get("count") or 0) for s in funnel) or 1
    label_f = _font(13, True)
    num_f = _font(13)
    bar_x0, bar_x1 = 210, width - pad

    for i, step in enumerate(funnel):
        y = top + i * row_h
        n = int(step.get("count") or 0)
        label = str(step.get("stage") or f"#{i}")
        draw.text((pad, y + 10), _fit(label, 22), font=label_f, fill=TEXT)
        bw = int((bar_x1 - bar_x0) * (n / max_n))
        draw.rounded_rectangle((bar_x0, y + 6, bar_x0 + max(bw, 2), y + 34), radius=6, fill=ACCENT)
        pct = step.get("pct_of_prev")
        right = f"{n}" + (f"  ({pct:g}% ←)" if pct is not None else "")
        draw.text((bar_x0 + max(bw, 2) + 8, y + 10), right, font=num_f, fill=MUTED)
    return _png(img)


def render_hbar_png(
    items: list[dict[str, Any]],
    *,
    title: str,
    subtitle: str = "",
    value_key: str = "reply_rate",
    count_key: str = "sent",
    max_rows: int = 12,
    value_suffix: str = "%",
    value_cap: float | None = 100.0,
) -> bytes:
    from PIL import Image, ImageDraw

    rows = [x for x in items if x.get(count_key) or x.get("attempts")][:max_rows]
    if not rows:
        return _blank(780, 300, title)

    width, row_h, pad = 780, 36, 24
    height = pad * 2 + 80 + row_h * len(rows) + 28
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    top = _header(draw, title, subtitle, width)
    label_f = _font(12, True)
    meta_f = _font(11)
    bar_x0, bar_x1 = 200, width - 110
    cap = value_cap if value_cap and value_cap > 0 else max(
        float(x.get(value_key) or 0) for x in rows
    ) or 1.0

    for i, row in enumerate(rows):
        y = top + i * row_h
        val = float(row.get(value_key) or 0)
        sent = int(row.get(count_key) or 0)
        responders = int(row.get("responders") or 0)
        label = str(row.get("label") or "—")
        draw.text((pad, y + 8), _fit(label, 24), font=label_f, fill=TEXT)
        bw = int((bar_x1 - bar_x0) * min(1.0, val / cap))
        color = GOOD if val >= 10 else (WARN if val >= 5 else ACCENT)
        draw.rounded_rectangle((bar_x0, y + 6, bar_x0 + max(bw, 2), y + 28), radius=5, fill=color)
        draw.rectangle((bar_x0, y + 6, bar_x1, y + 28), outline=GRID)
        draw.text(
            (bar_x1 + 8, y + 8),
            f"{val:g}{value_suffix}",
            font=label_f,
            fill=TEXT,
        )
        draw.text((bar_x0, y + 30), f"{responders}/{sent}", font=meta_f, fill=MUTED)
    return _png(img)


def render_timeline_png(
    daily: list[dict[str, Any]],
    *,
    title: str = "Динамика",
    subtitle: str = "",
    max_days: int = 30,
) -> bytes:
    from PIL import Image, ImageDraw

    days = daily[-max_days:] if daily else []
    if not days or not any(d.get("sent") or d.get("replies_received") for d in days):
        return _blank(860, 340, title)

    width, height, pad = 860, 360, 24
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    top = _header(draw, title, subtitle or "отправлено / ответы / редиректы", width)
    chart_top, chart_bot = top + 10, height - 48
    chart_left, chart_right = pad + 36, width - pad
    max_n = max(
        max(int(d.get("sent") or 0), int(d.get("replies_received") or 0), int(d.get("redirects_received") or 0))
        for d in days
    ) or 1
    n = len(days)
    gap = 4
    group_w = max(12, (chart_right - chart_left) // n - gap)
    bar_w = max(3, (group_w - 4) // 3)
    label_f = _font(10)
    legend_f = _font(11)

    for i, d in enumerate(days):
        x = chart_left + i * (group_w + gap)
        h_area = chart_bot - chart_top

        def bar(offset: int, value: int, color: tuple[int, int, int]) -> None:
            bh = int(h_area * (value / max_n))
            if bh <= 0 and value > 0:
                bh = 2
            y0 = chart_bot - bh
            draw.rectangle((x + offset, y0, x + offset + bar_w, chart_bot), fill=color)

        bar(0, int(d.get("sent") or 0), ACCENT)
        bar(bar_w + 1, int(d.get("replies_received") or 0), GOOD)
        bar(2 * (bar_w + 1), int(d.get("redirects_received") or 0), WARN)
        date = str(d.get("date") or "")[5:]
        if n <= 14 or i % max(1, n // 10) == 0 or i == n - 1:
            tw = _tw(label_f, date)
            draw.text((x + (group_w - tw) / 2, chart_bot + 6), date, font=label_f, fill=MUTED)

    # legend
    lx = pad
    for color, name in ((ACCENT, "отправлено"), (GOOD, "ответы"), (WARN, "редиректы")):
        draw.rectangle((lx, height - 28, lx + 12, height - 16), fill=color)
        draw.text((lx + 16, height - 30), name, font=legend_f, fill=MUTED)
        lx += 110
    draw.text((width - 120, height - 30), f"max {max_n}", font=legend_f, fill=MUTED)
    return _png(img)


def render_latency_png(
    latency: dict[str, Any],
    *,
    title: str = "Скорость ответа",
    subtitle: str = "",
) -> bytes:
    from PIL import Image, ImageDraw

    buckets = [b for b in (latency.get("buckets") or []) if b.get("count")]
    if not buckets:
        return _blank(720, 300, title, "Пока нет ответов с известным временем")

    width, row_h, pad = 720, 38, 24
    height = pad * 2 + 90 + row_h * len(buckets) + 40
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    med = latency.get("median")
    p90 = latency.get("p90")
    from app.analytics import fmt_duration

    sub = subtitle or (
        f"n={latency.get('n', 0)} · медиана {fmt_duration(med)} · p90 {fmt_duration(p90)}"
    )
    top = _header(draw, title, sub, width)
    label_f = _font(12, True)
    num_f = _font(12)
    bar_x0, bar_x1 = 180, width - pad
    max_pct = max(float(b.get("pct") or 0) for b in buckets) or 1.0

    for i, b in enumerate(buckets):
        y = top + i * row_h
        pct = float(b.get("pct") or 0)
        draw.text((pad, y + 8), _fit(str(b.get("label")), 18), font=label_f, fill=TEXT)
        bw = int((bar_x1 - bar_x0) * (pct / max_pct))
        draw.rounded_rectangle((bar_x0, y + 6, bar_x0 + max(bw, 2), y + 30), radius=5, fill=BAR_ALT)
        draw.text((bar_x0 + max(bw, 2) + 8, y + 8), f"{pct:g}% ({b['count']})", font=num_f, fill=MUTED)
    return _png(img)


def render_hours_png(
    hours: list[dict[str, Any]],
    *,
    title: str = "Когда пишут ответы",
    subtitle: str = "по местному часу",
) -> bytes:
    from PIL import Image, ImageDraw

    if not hours or not any(h.get("replies") for h in hours):
        return _blank(860, 300, title)

    width, height, pad = 860, 340, 24
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    top = _header(draw, title, subtitle, width)
    chart_top, chart_bot = top + 8, height - 40
    chart_left, chart_right = pad + 8, width - pad
    max_n = max(int(h.get("replies") or 0) for h in hours) or 1
    n = len(hours)
    slot = (chart_right - chart_left) / n
    label_f = _font(10)
    for i, h in enumerate(hours):
        x0 = chart_left + i * slot + 2
        x1 = chart_left + (i + 1) * slot - 2
        val = int(h.get("replies") or 0)
        bh = int((chart_bot - chart_top) * (val / max_n))
        color = ACCENT if val < max_n else GOOD
        if bh:
            draw.rectangle((x0, chart_bot - bh, x1, chart_bot), fill=color)
        if i % 2 == 0:
            lab = f"{int(h.get('hour', i)):02d}"
            tw = _tw(label_f, lab)
            draw.text((x0 + (x1 - x0 - tw) / 2, chart_bot + 6), lab, font=label_f, fill=MUTED)
    return _png(img)


def render_dashboard_png(report: dict[str, Any], period_label: str) -> bytes:
    """Сводная карточка: KPI + мини-воронка + топ офферов."""
    from PIL import Image, ImageDraw

    ov = report.get("overview") or {}
    funnel = report.get("funnel") or []
    offers = [x for x in (report.get("dims") or {}).get("text", []) if x.get("sent")][:5]
    lat = report.get("latency") or {}
    bl = report.get("backlog") or {}

    width, height = 900, 520
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    title_f = _font(20, True)
    sub_f = _font(12)
    kpi_f = _font(22, True)
    lab_f = _font(11)
    body_f = _font(13)

    draw.text((24, 18), "Outreach · отчёт", font=title_f, fill=HEADER)
    draw.text((24, 46), f"Период: {period_label}", font=sub_f, fill=MUTED)

    # KPI cards
    cards = [
        ("Отправлено", str(ov.get("sent", 0)), ACCENT),
        ("Ответили", f"{ov.get('responders', 0)} ({ov.get('reply_rate', 0):g}%)", GOOD),
        ("Доставка", f"{ov.get('delivery_rate', 0):g}%", BAR_ALT),
        ("Ждут ответа", str(bl.get("unanswered", 0)), WARN if bl.get("unanswered") else MUTED),
    ]
    cw = 200
    for i, (lab, val, color) in enumerate(cards):
        x0 = 24 + i * (cw + 12)
        y0 = 78
        draw.rounded_rectangle((x0, y0, x0 + cw, y0 + 72), radius=10, fill=PANEL, outline=GRID)
        draw.text((x0 + 14, y0 + 12), lab, font=lab_f, fill=MUTED)
        draw.text((x0 + 14, y0 + 32), _fit(val, 16), font=kpi_f, fill=color)

    # funnel mini
    draw.text((24, 170), "Воронка", font=_font(14, True), fill=HEADER)
    max_n = max((int(s.get("count") or 0) for s in funnel), default=1) or 1
    for i, step in enumerate(funnel):
        y = 198 + i * 28
        n = int(step.get("count") or 0)
        draw.text((24, y), _fit(str(step.get("stage")), 20), font=body_f, fill=TEXT)
        bw = int(280 * (n / max_n))
        draw.rounded_rectangle((210, y + 2, 210 + max(bw, 2), y + 18), radius=4, fill=ACCENT)
        draw.text((500, y), str(n), font=body_f, fill=MUTED)

    # top offers
    draw.text((24, 360), "Топ офферов по % ответов", font=_font(14, True), fill=HEADER)
    if not offers:
        draw.text((24, 390), "Нет данных", font=body_f, fill=MUTED)
    else:
        ranked = sorted(offers, key=lambda x: -float(x.get("reply_rate") or 0))
        for i, o in enumerate(ranked[:5]):
            y = 388 + i * 22
            draw.text(
                (24, y),
                f"{_fit(str(o.get('label')), 28)}  {o.get('reply_rate', 0):g}%  "
                f"({o.get('responders', 0)}/{o.get('sent', 0)})",
                font=body_f,
                fill=TEXT,
            )

    from app.analytics import fmt_duration

    med = lat.get("median")
    footer = f"Медиана до ответа: {fmt_duration(med)}" if med is not None else "Медиана до ответа: —"
    if ov.get("redirect_contacts"):
        footer += f" · редиректов {ov['redirect_contacts']}"
    draw.text((24, height - 28), footer, font=lab_f, fill=MUTED)
    return _png(img)


# ------------------------------------------------------------------ build set


def build_charts(report: dict[str, Any], period_label: str = "") -> dict[str, bytes]:
    """Все диаграммы отчёта: kind → PNG bytes."""
    dims = report.get("dims") or {}
    sub = period_label or "отчёт"
    return {
        "dashboard": render_dashboard_png(report, sub),
        "funnel": render_funnel_png(report.get("funnel") or [], title="Воронка", subtitle=sub),
        "offers": render_hbar_png(
            dims.get("text") or [], title="Офферы · % ответов", subtitle=sub
        ),
        "accounts": render_hbar_png(
            dims.get("account") or [], title="Аккаунты · % ответов", subtitle=sub
        ),
        "campaigns": render_hbar_png(
            dims.get("campaign") or [], title="Кампании · % ответов", subtitle=sub
        ),
        "timeline": render_timeline_png(report.get("daily") or [], title="Динамика", subtitle=sub),
        "latency": render_latency_png(
            report.get("latency") or {}, title="Скорость ответа клиента", subtitle=sub
        ),
        "hours": render_hours_png(
            report.get("reply_hours") or [], title="Когда пишут ответы", subtitle=sub
        ),
    }


def try_build_charts(report: dict[str, Any], period_label: str = "") -> dict[str, bytes]:
    try:
        return build_charts(report, period_label)
    except Exception:
        return {}


def try_chart(kind: str, report: dict[str, Any], period_label: str = "") -> bytes | None:
    if kind not in CHART_KINDS:
        return None
    try:
        return build_charts(report, period_label)[kind]
    except Exception:
        return None
