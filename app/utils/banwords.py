from __future__ import annotations

import re

# «r», «c», «js» и т.п. дают ложные матчи в любом чате
MIN_BANWORD_LEN = 3


def normalize_banword(word: str) -> str:
    return (word or "").strip()


def is_valid_banword(word: str) -> bool:
    w = normalize_banword(word)
    return len(w) >= MIN_BANWORD_LEN


def contains_banword(text: str, words: list[str]) -> str | None:
    """
    Целое слово/фраза, не подстрока.
    Слова короче 3 символов игнорируются.
    """
    if not text or not words:
        return None
    for word in words:
        w = normalize_banword(word)
        if not is_valid_banword(w):
            continue
        pattern = r"(?<!\w)" + re.escape(w) + r"(?!\w)"
        if re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE):
            return w
    return None
