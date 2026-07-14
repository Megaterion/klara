"""
metrics.py — Latency and performance tracking.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import AsyncIterator

logger = logging.getLogger(__name__)

# Keep last N samples per metric
WINDOW = 100


class Metrics:
    """
    Lightweight in-process metrics.
    Tracks p50/p95/p99 latency per named operation.
    """

    def __init__(self) -> None:
        self._samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=WINDOW))
        self._counters: dict[str, int] = defaultdict(int)

    def record(self, name: str, duration_ms: float) -> None:
        self._samples[name].append(duration_ms)
        self._counters[name] += 1
        logger.debug("metric %s = %.1f ms", name, duration_ms)

    def increment(self, name: str, value: int = 1) -> None:
        self._counters[name] += value

    def percentile(self, name: str, p: float = 0.95) -> float:
        """Return the p-th percentile of recorded durations, or 0 if no data."""
        samples = sorted(self._samples.get(name, []))
        if not samples:
            return 0.0
        idx = int(len(samples) * p)
        return samples[min(idx, len(samples) - 1)]

    def summary(self) -> dict:
        result = {}
        for name, samples in self._samples.items():
            s = sorted(samples)
            if s:
                result[name] = {
                    "count": self._counters[name],
                    "p50_ms": round(s[int(len(s) * 0.5)], 1),
                    "p95_ms": round(s[int(len(s) * 0.95)], 1),
                    "p99_ms": round(s[min(int(len(s) * 0.99), len(s) - 1)], 1),
                }
        return result

    @asynccontextmanager
    async def measure(self, name: str) -> AsyncIterator[None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - t0) * 1000
            self.record(name, elapsed)
