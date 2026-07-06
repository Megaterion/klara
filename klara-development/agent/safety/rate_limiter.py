"""
safety/rate_limiter.py – Token-bucket rate limiter for Klara's LLM and tool calls.

Prevents runaway cycles from hammering the Ollama API or external services.
"""

from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger(__name__)


class RateLimiter:
    """
    Simple token-bucket rate limiter.

    allows `rate` calls per `period` seconds.
    Callers await `acquire()` which blocks until a token is available.
    """

    def __init__(self, rate: float = 20.0, period: float = 60.0) -> None:
        self.rate = rate
        self.period = period
        self._tokens = rate
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, name: str = "call") -> None:
        async with self._lock:
            self._refill()
            if self._tokens >= 1:
                self._tokens -= 1
                return
            wait = (1 - self._tokens) * (self.period / self.rate)
            log.debug("Rate limiter: waiting %.1fs before '%s'", wait, name)
        await asyncio.sleep(wait)
        async with self._lock:
            self._refill()
            self._tokens = max(0.0, self._tokens - 1)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.rate, self._tokens + elapsed * (self.rate / self.period))
        self._last_refill = now

    @property
    def available(self) -> float:
        self._refill()
        return self._tokens
