"""
In-process async event bus.

Simple. No Kafka. No Redis pub/sub. Just asyncio for day 1.
Departments interact with EventBusProtocol, not the implementation.
Swappable to Redis/NATS later without changing department code.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine, Protocol

from src.models.events import Event

logger = logging.getLogger(__name__)

Handler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBusProtocol(Protocol):
    """Contract that departments depend on. Implementation is swappable."""

    async def publish(self, event: Event) -> None: ...
    def subscribe(self, event_type: str, handler: Handler) -> None: ...
    def unsubscribe(self, event_type: str, handler: Handler) -> None: ...


class InProcessEventBus:
    """
    Async in-process event bus.
    Handlers run concurrently via asyncio.gather.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._history: list[Event] = []
        self._max_history: int = 1000

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type].append(handler)
        handler_name = getattr(handler, "__qualname__", repr(handler))
        logger.debug("Subscribed %s to %s", handler_name, event_type)

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type].remove(handler)

    async def publish(self, event: Event) -> None:
        logger.info("Event: %s (id=%s)", event.event_type, event.id)
        self._record(event)

        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            return

        results = await asyncio.gather(
            *(h(event) for h in handlers),
            return_exceptions=True,
        )

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Handler %s failed for %s: %s",
                    handlers[i].__qualname__,
                    event.event_type,
                    result,
                )

    def _record(self, event: Event) -> None:
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    @property
    def history(self) -> list[Event]:
        return list(self._history)
