"""
observability/tracing.py – Structured logging and trace context for Klara.

Provides a TraceContext for each reasoning cycle that enriches log records
with cycle_id, user_id, event_type for easy filtering.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator

# Module-level logger
log = logging.getLogger(__name__)


def configure_logging(level: str = "INFO") -> None:
    """Set up structured logging format for Klara."""
    fmt = "%(asctime)s [%(levelname)-8s] %(name)s | cycle=%(cycle_id)s | %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
    )
    # Add default cycle_id to root logger
    logging.getLogger().handlers[0].addFilter(_CycleIdFilter("startup"))


class _CycleIdFilter(logging.Filter):
    def __init__(self, cycle_id: str = "none") -> None:
        super().__init__()
        self.cycle_id = cycle_id

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "cycle_id"):
            record.cycle_id = self.cycle_id  # type: ignore[attr-defined]
        return True


@dataclass
class TraceContext:
    cycle_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    user_id: str = "unknown"
    event_type: str = "timer"
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "user_id": self.user_id,
            "event_type": self.event_type,
            **self.extra,
        }


@contextmanager
def cycle_trace(
    user_id: str = "unknown",
    event_type: str = "timer",
) -> Generator[TraceContext, None, None]:
    """
    Context manager that creates a TraceContext for one reasoning cycle.
    Logs start/end automatically.
    """
    ctx = TraceContext(user_id=user_id, event_type=event_type)
    log.debug("Cycle %s started (event=%s, user=%s)", ctx.cycle_id, event_type, user_id)
    try:
        yield ctx
    except Exception as exc:
        log.error("Cycle %s failed: %s", ctx.cycle_id, exc)
        raise
    else:
        log.debug("Cycle %s completed.", ctx.cycle_id)
