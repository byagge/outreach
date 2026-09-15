from __future__ import annotations

import random
from dataclasses import dataclass

from app.models import Account, Contact, Proxy, TextVariant


@dataclass
class Plan:
    text: TextVariant
    typing_seconds: float
    pre_pause: float
    think: str


def typing_seconds(text: str, enabled: bool = True) -> float:
    if not enabled:
        return 0.35
    n = max(len(text or ""), 8)
    cps = random.uniform(4.8, 8.2)
    sec = n / cps + random.uniform(0.55, 2.1)
    return float(min(max(sec, 1.15), 9.4))


def between_messages(lo: int, hi: int) -> float:
    lo = max(1, int(lo))
    hi = max(lo, int(hi))
    mid = (lo + hi) / 2
    spread = max((hi - lo) / 3.4, 1.0)
    val = random.gauss(mid, spread)
    return float(min(max(val, lo), hi))


def between_accounts(lo: int, hi: int) -> float:
    lo = max(0, int(lo))
    hi = max(lo, int(hi))
    if hi <= 0:
        return 0.0
    if lo == hi:
        return float(lo)
    mid = (lo + hi) / 2
    spread = max((hi - lo) / 3.4, 0.25)
    val = random.gauss(mid, spread)
    return float(min(max(val, lo), hi))


def pick_variant(texts: list[TextVariant], mode: str, sent_count: int) -> TextVariant:
    live = [
        t
        for t in texts
        if t.enabled and ((t.text or "").strip() or (t.photo_path or "").strip())
    ]
    if not live:
        raise RuntimeError("Нет включённых текстов")
    if mode == "random":
        return random.choice(live)
    return live[sent_count % len(live)]


def plan_send(
    contact: Contact,
    texts: list[TextVariant],
    account: Account,
    proxy: Proxy | None,
    *,
    sent_count: int,
    typing: bool,
    variant_mode: str,
) -> Plan:
    text = pick_variant(texts, variant_mode, sent_count)
    wait = typing_seconds(text.text, typing)
    pre = random.uniform(0.35, 1.6)
    proxy_s = proxy.label if proxy else "без прокси"
    kind_ru = {
        "username": "username",
        "user_id": "числовой id",
        "phone": "телефон",
        "unknown": "непонятный контакт",
    }.get(contact.kind, contact.kind)
    think = (
        f"контакт {contact.pretty} — это {kind_ru}; "
        f"пишу с {account.label} через {proxy_s}; "
        f"вариант текста #{text.id}"
        f"{(' «' + text.title + '»') if text.title else ''}; "
        f"печатаю {wait:.1f}с как человек, потом отправляю целиком"
    )
    return Plan(text=text, typing_seconds=wait, pre_pause=pre, think=think)
