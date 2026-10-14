from __future__ import annotations

import re
from typing import Any

# Известные TLD — чтобы «привет.как дела» не считалось ссылкой, а «site.ru» — считалось.
_TLDS = (
    "com|ru|org|net|io|me|app|ly|co|xyz|info|biz|su|ua|by|kz|uz|kg|top|site|online|shop|store|"
    "club|link|click|live|pro|dev|ai|gg|cc|tv|fm|to|so|vip|cloud|tech|space|fun|one|world|"
    "page|wiki|bio|team|group|chat|bot|cn|de|uk|us|eu|in|fr|it|es|pl|tr|ir|id|vn|th"
)

_URL_RE = re.compile(
    r"(?:https?://|ftp://|tg://|www\.|//[a-z0-9])"
    r"|(?:\b(?:t|telegram)\.me/)"
    r"|(?:\btelegra\.ph/)"
    rf"|(?:\b[a-z0-9][a-z0-9\-]{{0,62}}(?:\.[a-z0-9\-]{{1,63}})*\.(?:{_TLDS})(?![a-z0-9\-])(?:[/?#:]|\b))",
    re.IGNORECASE,
)

_LINK_ENTITY_TYPES = {
    "url",
    "text_link",
    "messageentityurl",
    "messageentitytexturl",
}


def _entity_is_link(ent: Any) -> bool:
    if isinstance(ent, dict):
        kind = str(ent.get("type", ""))
    else:
        kind = ent.__class__.__name__
    return kind.lower() in _LINK_ENTITY_TYPES


def has_link(text: str | None, entities: list[Any] | None = None, *, web_preview: bool = False) -> bool:
    """
    True, если сообщение содержит ссылку (и значит это редирект/реклама, а не живой ответ).

    Проверяем: url/text_link entities, превью страницы, и regex по тексту
    (http(s)://, www., t.me/…, домены с известными TLD).
    """
    if web_preview:
        return True
    for ent in entities or []:
        if _entity_is_link(ent):
            return True
    if not text:
        return False
    return bool(_URL_RE.search(text))
