"""
task_queue.py — Async priority queue for sub-agent tasks.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from agent.schemas.assessment import SubAgentTask, TaskPriority

logger = logging.getLogger(__name__)

_PRIORITY_MAP = {
    TaskPriority.HIGH: 0,
    TaskPriority.NORMAL: 1,
    TaskPriority.LOW: 2,
}


@dataclass(order=True)
class _QueueItem:
    priority_val: int
    seq: int  # tie-breaker: insertion order
    task: SubAgentTask = field(compare=False)


class TaskQueue:
    """Priority queue for SubAgentTasks. Higher-priority tasks run first."""

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[_QueueItem] = asyncio.PriorityQueue()
        self._seq = 0

    async def enqueue(self, task: SubAgentTask) -> None:
        pval = _PRIORITY_MAP.get(task.priority, 1)
        item = _QueueItem(priority_val=pval, seq=self._seq, task=task)
        self._seq += 1
        await self._queue.put(item)
        logger.debug("Queued task: %s.%s (priority=%s)", task.agent, task.action, task.priority)

    async def dequeue(self, timeout: float = 1.0) -> Optional[SubAgentTask]:
        try:
            item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            return item.task
        except asyncio.TimeoutError:
            return None

    def task_done(self) -> None:
        self._queue.task_done()

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    async def drain(self, max_items: int = 10) -> list[SubAgentTask]:
        """Drain up to max_items tasks from the queue."""
        tasks = []
        while not self.empty() and len(tasks) < max_items:
            task = await self.dequeue(timeout=0.01)
            if task:
                tasks.append(task)
        return tasks
