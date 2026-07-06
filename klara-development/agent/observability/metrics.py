"""
observability/metrics.py – Lightweight metrics collection for Klara.

Tracks KPIs defined in the v3 roadmap:
- Planner latency p95 <= 1.5s
- End-to-End latency p95 <= 3.5s
- JSON validation success rate >= 99%
- Memory retrieval hit rate >= 70%

Exposes a /metrics endpoint (optional Prometheus) and logs summaries periodically.
"""

from __future__ import annotations

import logging
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

_MAX_SAMPLES = 1000  # rolling window


@dataclass
class LatencyTracker:
    name: str
    _samples: deque = field(default_factory=lambda: deque(maxlen=_MAX_SAMPLES))

    def record(self, seconds: float) -> None:
        self._samples.append(seconds)

    def p95(self) -> float | None:
        if len(self._samples) < 2:
            return None
        return statistics.quantiles(list(self._samples), n=20)[18]  # 95th percentile

    def mean(self) -> float | None:
        if not self._samples:
            return None
        return statistics.mean(self._samples)

    def count(self) -> int:
        return len(self._samples)


class Counter:
    def __init__(self, name: str) -> None:
        self.name = name
        self._value = 0

    def inc(self, amount: int = 1) -> None:
        self._value += amount

    @property
    def value(self) -> int:
        return self._value


class KlaraMetrics:
    def __init__(self) -> None:
        self.planner_latency = LatencyTracker("planner_latency_seconds")
        self.e2e_latency = LatencyTracker("e2e_latency_seconds")
        self.tts_latency = LatencyTracker("tts_latency_seconds")
        self.memory_retrieval_latency = LatencyTracker("memory_retrieval_latency_seconds")

        self.cycles_total = Counter("cycles_total")
        self.cycles_interacted = Counter("cycles_interacted")
        self.json_valid = Counter("json_valid_total")
        self.json_invalid = Counter("json_invalid_total")
        self.memory_hits = Counter("memory_hits_total")
        self.memory_misses = Counter("memory_misses_total")
        self.tool_calls = Counter("tool_calls_total")
        self.tool_errors = Counter("tool_errors_total")

    # ------------------------------------------------------------------
    # Computed KPIs
    # ------------------------------------------------------------------

    def json_validation_rate(self) -> float:
        total = self.json_valid.value + self.json_invalid.value
        return self.json_valid.value / total if total > 0 else 1.0

    def memory_hit_rate(self) -> float:
        total = self.memory_hits.value + self.memory_misses.value
        return self.memory_hits.value / total if total > 0 else 0.0

    # ------------------------------------------------------------------
    # Summary logging
    # ------------------------------------------------------------------

    def log_summary(self) -> None:
        log.info(
            "=== Klara Metrics Summary ===\n"
            "  Cycles: %d total, %d interactive\n"
            "  JSON validation rate: %.1f%%\n"
            "  Memory hit rate: %.1f%%\n"
            "  Planner p95: %s\n"
            "  E2E p95: %s\n"
            "  Tool calls: %d (%d errors)",
            self.cycles_total.value,
            self.cycles_interacted.value,
            self.json_validation_rate() * 100,
            self.memory_hit_rate() * 100,
            f"{self.planner_latency.p95():.3f}s" if self.planner_latency.p95() else "n/a",
            f"{self.e2e_latency.p95():.3f}s" if self.e2e_latency.p95() else "n/a",
            self.tool_calls.value,
            self.tool_errors.value,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycles_total": self.cycles_total.value,
            "cycles_interacted": self.cycles_interacted.value,
            "json_validation_rate": self.json_validation_rate(),
            "memory_hit_rate": self.memory_hit_rate(),
            "planner_latency_p95_s": self.planner_latency.p95(),
            "e2e_latency_p95_s": self.e2e_latency.p95(),
            "tool_calls_total": self.tool_calls.value,
            "tool_errors_total": self.tool_errors.value,
        }


# Context manager helper for timing
class timer:  # noqa: N801
    def __init__(self, tracker: LatencyTracker) -> None:
        self._tracker = tracker
        self._start: float = 0.0

    def __enter__(self) -> "timer":
        self._start = time.monotonic()
        return self

    def __exit__(self, *_: Any) -> None:
        self._tracker.record(time.monotonic() - self._start)
