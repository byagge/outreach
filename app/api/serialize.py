from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if is_dataclass(obj) and not isinstance(obj, type):
        data = asdict(obj)
        # enrich common computed fields
        for attr in ("pretty", "display", "label", "has_telethon", "on"):
            if hasattr(obj, attr):
                try:
                    data[attr] = getattr(obj, attr)
                except Exception:
                    pass
        return data
    if isinstance(obj, list):
        return [to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj
