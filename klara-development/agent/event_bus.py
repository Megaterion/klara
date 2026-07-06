"""
event_bus.py – Async event bus for Klara.

Distributes events from multiple sources (timer, HA WebSocket, user input,
motion triggers) to registered handlers without tight coupling.

Each event has a type and an optional payload.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

log = logging.getLogger(__name__)


class EventType(str, Enum):
    TIMER = "timer"
    USER_INPUT = "user_input"
    SMARTHOME_STATE_CHANGE = "smarthome_state_change"
    MOTION_DETECTED = "motion_detected"
    SYSTEM_STARTUP = "system_startup"
    SHUTDOWN = "shutdown"
    MEMORY_CONSOLIDATION = "memory_consolidation"


@dataclass
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"


Handler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """
    Simple async pub/sub event bus.

    - publish(event): enqueue an event for delivery.
    - subscribe(event_type, handler): register a coroutine handler.
    - run(): consume and dispatch events until stopped.
    """

    def __init__(self, maxsize: int = 256) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._handlers: dict[EventType, list[Handler]] = {}
        self._running = False

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)
        log.debug("Subscribed handler '%s' to %s", handler.__name__, event_type)

    async def publish(self, event: Event) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("EventBus queue full – dropping event %s from %s", event.type, event.source)

    async def run(self) -> None:
        self._running = True
        log.info("EventBus started.")
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            await self._dispatch(event)
            self._queue.task_done()

    async def _dispatch(self, event: Event) -> None:
        handlers = self._handlers.get(event.type, [])
        if not handlers:
            log.debug("No handlers for event type %s", event.type)
            return
        for handler in handlers:
            try:
                await handler(event)
            except Exception as exc:
                log.error("Handler '%s' raised for event %s: %s", handler.__name__, event.type, exc)

    def stop(self) -> None:
        self._running = False
        log.info("EventBus stopping.")
