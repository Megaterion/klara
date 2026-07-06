"""
safety/tool_budget.py – Per-cycle tool call budget enforcement.

Prevents infinite LLM tool-calling loops and GPU overload.
Each reasoning cycle gets a fresh budget; exceeding it aborts execution.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class CycleBudget:
    max_tool_calls: int
    tool_timeout_seconds: float
    llm_timeout_seconds: float
    _calls_used: int = field(default=0, init=False)
    _start_time: float = field(default_factory=time.monotonic, init=False)

    def consume(self, tool_name: str) -> bool:
        """
        Attempt to consume one tool call from the budget.
        Returns True if allowed, False if budget is exhausted.
        """
        if self._calls_used >= self.max_tool_calls:
            log.warning(
                "Tool budget exhausted (%d/%d) – blocked call to '%s'.",
                self._calls_used,
                self.max_tool_calls,
                tool_name,
            )
            return False
        self._calls_used += 1
        log.debug("Tool budget: %d/%d used (calling '%s')", self._calls_used, self.max_tool_calls, tool_name)
        return True

    @property
    def remaining(self) -> int:
        return max(0, self.max_tool_calls - self._calls_used)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start_time

    def is_cycle_timeout(self) -> bool:
        return self.elapsed > self.llm_timeout_seconds * 2


class ToolBudget:
    """
    Factory that creates a fresh CycleBudget for every reasoning cycle.
    """

    def __init__(
        self,
        max_tool_calls: int = 3,
        tool_timeout_seconds: float = 15.0,
        llm_timeout_seconds: float = 30.0,
    ) -> None:
        self.max_tool_calls = max_tool_calls
        self.tool_timeout = tool_timeout_seconds
        self.llm_timeout = llm_timeout_seconds

    def new_cycle(self) -> CycleBudget:
        return CycleBudget(
            max_tool_calls=self.max_tool_calls,
            tool_timeout_seconds=self.tool_timeout,
            llm_timeout_seconds=self.llm_timeout,
        )
