from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


def parse_hhmm(raw: str) -> time | None:
    text = (raw or "").strip()
    if not text:
        return None
    parts = text.replace(".", ":").split(":")
    if len(parts) < 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


def parse_work_hours(raw: str) -> tuple[str, str] | None:
    """Return ('HH:MM','HH:MM') or ('','') for 24/7. None if invalid."""
    text = (raw or "").strip()
    if not text or text in {"-", "24/7", "24", "0", "off"}:
        return "", ""
    parts = text.replace("—", "-").replace("–", "-").split("-", 1)
    if len(parts) != 2:
        return None
    start = parse_hhmm(parts[0].strip())
    end = parse_hhmm(parts[1].strip())
    if start is None or end is None:
        return None
    return f"{start.hour:02d}:{start.minute:02d}", f"{end.hour:02d}:{end.minute:02d}"


def in_work_hours(work_start: str, work_end: str, tz: ZoneInfo) -> bool:
    start = parse_hhmm(work_start)
    end = parse_hhmm(work_end)
    if start is None or end is None:
        return True
    now = datetime.now(tz).time()
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end
