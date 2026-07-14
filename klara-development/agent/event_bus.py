"""
event_bus.py — Lightweight async pub/sub event bus.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

EventHandler = Callable[..., Coroutine[Any, Any, None]]


class EventBus:
    """
    Simple async pub/sub.
    Handlers are awaited in subscription order.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event: str, handler: EventHandler) -> None:
        self._handlers[event].append(handler)
        logger.debug("Subscribed %s to event '%s'", handler.__name__, event)

    def unsubscribe(self, event: str, handler: EventHandler) -> None:
        try:
            self._handlers[event].remove(handler)
        except ValueError:
            pass

    async def publish(self, event: str, **kwargs: Any) -> None:
        handlers = list(self._handlers.get(event, []))
        if not handlers:
            logger.debug("No handlers for event '%s'", event)
            return
        logger.debug("Publishing event '%s' to %d handler(s)", event, len(handlers))
        for handler in handlers:
            try:
                await handler(**kwargs)
            except Exception as exc:
                logger.error("Handler %s failed for event '%s': %s", handler.__name__, event, exc)

    async def publish_nowait(self, event: str, **kwargs: Any) -> None:
        """Fire-and-forget: schedule handlers as tasks."""
        handlers = list(self._handlers.get(event, []))
        for handler in handlers:
            asyncio.create_task(handler(**kwargs), name=f"event.{event}")


# Well-known event names
class Events:
    USER_SPEECH = "user.speech"           # user spoke; data: text=str
    KLARA_RESPONSE = "klara.response"     # Klara has a response; data: text=str
    KLARA_TOKEN = "klara.token"           # streaming token; data: token=str
    TOOL_CALLED = "tool.called"           # tool invoked; data: tool=str, params=dict
    TOOL_RESULT = "tool.result"           # tool finished; data: tool=str, result=ToolResult
    CYCLE_START = "cycle.start"           # new orchestration cycle started
    CYCLE_END = "cycle.end"               # cycle finished
    SHUTDOWN = "system.shutdown"          # clean shutdown requested
