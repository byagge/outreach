from __future__ import annotations


def contains_banword(text: str, words: list[str]) -> str | None:
    if not text or not words:
        return None
    low = text.casefold()
    for word in words:
        w = (word or "").strip()
        if not w:
            continue
        if w.casefold() in low:
            return w
    return None
