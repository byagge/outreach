from __future__ import annotations

import re


def contains_banword(text: str, words: list[str]) -> str | None:
    """
    Целое слово/фраза, не подстрока.
    «dev» не матчит «device»; «код» не матчит «кодекс».
    """
    if not text or not words:
        return None
    for word in words:
        w = (word or "").strip()
        if not w:
            continue
        # слишком короткие (1–2) — только точное целое слово, всё равно через границы
        pattern = r"(?<!\w)" + re.escape(w) + r"(?!\w)"
        if re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE):
            return w
    return None
