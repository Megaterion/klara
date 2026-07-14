"""
tool_budget.py — Per-cycle tool call budget enforcement.
Prevents runaway LLM tool cascades.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ToolBudget:
    """
    Tracks tool calls within a single orchestration cycle.
    Reset at the start of each cycle.
    """

    max_calls: int = 3
    _calls: int = field(default=0, init=False, repr=False)
    _call_log: list[str] = field(default_factory=list, init=False, repr=False)

    def reset(self) -> None:
        self._calls = 0
        self._call_log.clear()

    def can_call(self, tool_name: str = "") -> bool:
        if self._calls >= self.max_calls:
            logger.warning(
                "Tool budget exhausted (%d/%d). Blocked: %s",
                self._calls,
                self.max_calls,
                tool_name,
            )
            return False
        return True

    def record_call(self, tool_name: str) -> None:
        self._calls += 1
        self._call_log.append(tool_name)
        logger.debug("Tool call %d/%d: %s", self._calls, self.max_calls, tool_name)

    @property
    def calls_used(self) -> int:
        return self._calls

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self._calls)

    @property
    def call_log(self) -> list[str]:
        return list(self._call_log)
