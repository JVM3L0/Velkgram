"""Core ports used across modules."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol, TypeVar

from velkgram.shared.events import Event

E = TypeVar("E", bound=Event)


class Clock(Protocol):
    def now(self) -> datetime: ...


class EventBus(Protocol):
    def publish(self, event: Event) -> Awaitable[None]: ...

    def subscribe(self, event_type: type[E], handler: Callable[[E], Awaitable[None]]) -> None: ...

    def run(self) -> Awaitable[None]:
        """Dispatch until cancelled."""
        ...

    def drain(self) -> Awaitable[None]:
        """Dispatch until the queue is empty."""
        ...


class ChangeSignal(Protocol):
    def changed(self) -> Awaitable[dict[str, int]]:
        """Names whose version changed since the previous call, with the new version."""
        ...
