from __future__ import annotations

import asyncio
import socket

from app.models import Proxy
from app.tg.client import telethon_proxy


async def check_proxy(proxy: Proxy, timeout: float = 12.0) -> tuple[bool, str]:
    scheme = (proxy.scheme or "socks5").lower()
    if scheme == "mtproto":
        return False, "MTProto проверяется только при отправке"
    tp = telethon_proxy(proxy)
    if not tp:
        return False, "Не удалось разобрать прокси"
    kind, host, port, rdns, user, password = tp

    def _probe() -> None:
        import socks  # type: ignore

        s = socks.socksocket()
        s.settimeout(timeout)
        s.set_proxy(kind, host, port, rdns=rdns, username=user, password=password)
        try:
            s.connect(("149.154.167.50", 443))
        finally:
            s.close()

    try:
        await asyncio.wait_for(asyncio.to_thread(_probe), timeout=timeout + 2)
        return True, "OK — соединение с Telegram установлено"
    except asyncio.TimeoutError:
        return False, "Таймаут"
    except socket.error as e:
        return False, str(e)[:200]
    except Exception as e:
        return False, str(e)[:200]
