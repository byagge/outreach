from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from telethon import TelegramClient
from telethon.network.connection.tcpmtproxy import ConnectionTcpMTProxyRandomizedIntermediate
from telethon.tl.types import User

from app.config import get_settings
from app.models import Proxy


def session_stem(path: str | Path) -> str:
    p = Path(path)
    if p.suffix == ".session":
        return str(p.with_suffix(""))
    return str(p)


def telethon_proxy(proxy: Proxy | None):
    if not proxy:
        return None
    scheme = (proxy.scheme or "socks5").lower()
    if scheme == "mtproto":
        return (proxy.host, int(proxy.port), proxy.password or proxy.username)
    try:
        import socks
    except ImportError as e:
        raise RuntimeError("Нужен пакет PySocks для прокси") from e
    kind = {
        "socks5": socks.SOCKS5,
        "socks4": socks.SOCKS4,
        "http": socks.HTTP,
        "https": socks.HTTP,
    }.get(scheme, socks.SOCKS5)
    user = proxy.username or None
    password = proxy.password or None
    return (kind, proxy.host, int(proxy.port), True, user, password)


@asynccontextmanager
async def telethon_client(
    session_path: str | Path,
    proxy: Proxy | None = None,
) -> AsyncIterator[TelegramClient]:
    settings = get_settings()
    kwargs: dict = {
        "connection_retries": 3,
        "retry_delay": 2,
        "timeout": 25,
    }
    if proxy and (proxy.scheme or "").lower() == "mtproto":
        kwargs["connection"] = ConnectionTcpMTProxyRandomizedIntermediate
        kwargs["proxy"] = telethon_proxy(proxy)
    else:
        kwargs["proxy"] = telethon_proxy(proxy)
    client = TelegramClient(
        session_stem(session_path),
        settings.api_id,
        settings.api_hash,
        **kwargs,
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Session не авторизована. Загрузите валидный Telethon .session")
        yield client
    finally:
        await client.disconnect()


async def inspect_session(session_path: str | Path, proxy: Proxy | None = None) -> dict:
    async with telethon_client(session_path, proxy) as client:
        me = await client.get_me()
        assert isinstance(me, User)
        return {
            "user_id": int(me.id),
            "username": me.username or "",
            "phone": me.phone or "",
            "first_name": me.first_name or "",
            "premium": bool(getattr(me, "premium", False)),
        }
