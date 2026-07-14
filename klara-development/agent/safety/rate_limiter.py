"""
rate_limiter.py — Token-bucket rate limiter for API calls.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token-bucket rate limiter.
    Tracks separate buckets per tool/endpoint name.
    """

    def __init__(self, rate: float = 1.0, burst: int = 3) -> None:
        """
        rate: tokens refilled per second
        burst: maximum tokens in bucket
        """
        self.rate = rate
        self.burst = burst
        self._tokens: dict[str, float] = defaultdict(lambda: float(burst))
        self._last_refill: dict[str, float] = defaultdict(time.monotonic)

    def _refill(self, key: str) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill[key]
        self._tokens[key] = min(self.burst, self._tokens[key] + elapsed * self.rate)
        self._last_refill[key] = now

    def is_allowed(self, key: str) -> bool:
        self._refill(key)
        if self._tokens[key] >= 1.0:
            self._tokens[key] -= 1.0
            return True
        logger.warning("Rate limit hit for: %s", key)
        return False

    async def acquire(self, key: str) -> None:
        """Async wait until a token is available."""
        while not self.is_allowed(key):
            wait = 1.0 / self.rate
            logger.debug("Rate limited on %s, waiting %.2fs", key, wait)
            await asyncio.sleep(wait)
