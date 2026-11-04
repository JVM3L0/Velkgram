import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from velkgram.shared.events import Event
from velkgram.shared.ports import E

log = logging.getLogger(__name__)

_Handler = Callable[[Any], Awaitable[None]]


class MemoryBus:
    """In-process bus: unbounded queue, handlers awaited in subscription order."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._handlers: defaultdict[type, list[_Handler]] = defaultdict(list)

    async def publish(self, event: Event) -> None:
        self._queue.put_nowait(event)

    def subscribe(self, event_type: type[E], handler: Callable[[E], Awaitable[None]]) -> None:
        self._handlers[event_type].append(handler)

    async def _dispatch(self, event: Event) -> None:
        for handler in self._handlers.get(type(event), []):
            try:
                await handler(event)
            except Exception:
                log.exception(
                    "event_handler_failed",
                    extra={"event_type": type(event).__name__},
                )

    async def run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self._dispatch(event)
            finally:
                self._queue.task_done()

    async def drain(self) -> None:
        while not self._queue.empty():
            event = self._queue.get_nowait()
            try:
                await self._dispatch(event)
            finally:
                self._queue.task_done()
