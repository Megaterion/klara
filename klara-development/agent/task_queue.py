"""
task_queue.py – Priority-based task queue for Klara's sub-agent execution.

Priority levels (from roadmap):
  0 = Critical   (e.g. alarm, safety)
  1 = High        (e.g. direct user request)
  2 = Normal      (e.g. proactive assistant action)
  3 = Background  (e.g. memory consolidation, cache warm-up)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from .schemas.assessment import SubAgentTask

log = logging.getLogger(__name__)


@dataclass(order=True)
class PrioritizedTask:
    priority: int
    task: SubAgentTask = field(compare=False)


class TaskQueue:
    """
    Async priority queue that holds SubAgentTasks ordered by priority.

    Lower priority number = processed first.
    """

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[PrioritizedTask] = asyncio.PriorityQueue()

    async def enqueue(self, task: SubAgentTask) -> None:
        await self._queue.put(PrioritizedTask(priority=task.priority, task=task))
        log.debug("Enqueued task: %s/%s (priority=%d)", task.sub_agent_name, task.action, task.priority)

    async def enqueue_all(self, tasks: list[SubAgentTask]) -> None:
        for task in tasks:
            await self.enqueue(task)

    async def dequeue(self) -> SubAgentTask:
        item = await self._queue.get()
        self._queue.task_done()
        return item.task

    async def drain(self) -> list[SubAgentTask]:
        """Return all currently queued tasks (non-blocking, empties the queue)."""
        tasks: list[SubAgentTask] = []
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                self._queue.task_done()
                tasks.append(item.task)
            except asyncio.QueueEmpty:
                break
        return tasks

    @property
    def size(self) -> int:
        return self._queue.qsize()

    def is_empty(self) -> bool:
        return self._queue.empty()
