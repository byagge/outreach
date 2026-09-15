from __future__ import annotations

import asyncio
import time

from app.ai.brain import between_accounts
from app.models import OutreachSettings


class SendCoordinator:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_send = 0.0
        self._reserved_until = 0.0

    async def wait_between_accounts(self, settings: OutreachSettings) -> None:
        lo = max(0, int(settings.between_delay_min))
        hi = max(lo, int(settings.between_delay_max))
        if hi <= 0 and lo <= 0:
            return

        while True:
            async with self._lock:
                now = time.monotonic()
                delay = between_accounts(lo, hi)
                target = max(self._last_send, self._reserved_until) + delay
                wait = target - now
                if wait <= 0:
                    self._reserved_until = now
                    return
                self._reserved_until = target
            await asyncio.sleep(wait)

    async def mark_sent(self) -> None:
        async with self._lock:
            self._last_send = time.monotonic()


coordinator = SendCoordinator()
