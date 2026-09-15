from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from app.config import get_settings
from app.context import ctx
from app.store import Store


async def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    settings = get_settings()
    expected = (settings.api_key or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API_KEY не задан в .env — API отключён",
        )
    if not x_api_key or x_api_key.strip() != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def get_store() -> Store:
    store = getattr(ctx, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Store not initialized")
    return store


StoreDep = Depends(get_store)
AuthDep = Depends(require_api_key)
