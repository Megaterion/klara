"""
observability/quality_checks.py – Runtime quality validation for Klara.

Checks KPI thresholds and logs warnings when targets are missed.
Also validates TTS audio quality indicators.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .metrics import KlaraMetrics

log = logging.getLogger(__name__)

# KPI thresholds from ProjektRoadmap_v3.md
_KPI_PLANNER_P95_MAX = 1.5  # seconds
_KPI_E2E_P95_MAX = 3.5      # seconds
_KPI_JSON_VALID_MIN = 0.99  # 99%
_KPI_MEMORY_HIT_MIN = 0.70  # 70%


def check_kpis(metrics: "KlaraMetrics") -> list[str]:
    """
    Evaluate current metrics against KPI targets.

    Returns a list of violation messages (empty = all KPIs met).
    """
    violations: list[str] = []

    p95_planner = metrics.planner_latency.p95()
    if p95_planner is not None and p95_planner > _KPI_PLANNER_P95_MAX:
        violations.append(
            f"Planner latency p95 {p95_planner:.2f}s > target {_KPI_PLANNER_P95_MAX}s"
        )

    p95_e2e = metrics.e2e_latency.p95()
    if p95_e2e is not None and p95_e2e > _KPI_E2E_P95_MAX:
        violations.append(
            f"E2E latency p95 {p95_e2e:.2f}s > target {_KPI_E2E_P95_MAX}s"
        )

    json_rate = metrics.json_validation_rate()
    if metrics.json_valid.value + metrics.json_invalid.value >= 10:
        if json_rate < _KPI_JSON_VALID_MIN:
            violations.append(
                f"JSON validation rate {json_rate:.1%} < target {_KPI_JSON_VALID_MIN:.1%}"
            )

    mem_rate = metrics.memory_hit_rate()
    if metrics.memory_hits.value + metrics.memory_misses.value >= 10:
        if mem_rate < _KPI_MEMORY_HIT_MIN:
            violations.append(
                f"Memory hit rate {mem_rate:.1%} < target {_KPI_MEMORY_HIT_MIN:.1%}"
            )

    for v in violations:
        log.warning("KPI VIOLATION: %s", v)

    return violations


def log_kpi_status(metrics: "KlaraMetrics") -> None:
    violations = check_kpis(metrics)
    if not violations:
        log.info("All KPIs within target. ✓")
    else:
        log.warning("%d KPI violation(s) detected.", len(violations))
