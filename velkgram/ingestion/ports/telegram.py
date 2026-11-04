"""Telegram gateway port (the Telethon adapter lives in the collector app)."""

from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from velkgram.shared.events import MessageData


@dataclass(frozen=True, slots=True)
class ResolvedChannel:
    telegram_id: int
    title: str


class ChannelResolutionError(Exception):
    """The channel reference could not be resolved or joined (pt-BR message)."""


class TelegramDeferred(Exception):
    """Flood wait over 60 s: the caller logs `telegram_deferred` and moves on."""

    def __init__(self, seconds: int) -> None:
        super().__init__(f"Telegram pediu para aguardar {seconds}s")
        self.seconds = seconds


class TelegramGateway(Protocol):
    def iter_since(
        self, channel_id: int, min_id: int | None, limit: int, not_before: datetime
    ) -> AsyncIterator[MessageData]:
        """Yield messages newer than `min_id` and not older than `not_before`, oldest first."""
        ...

    def latest_message_id(self, channel_id: int) -> Awaitable[int | None]: ...

    def resolve_and_join(self, ref: str) -> Awaitable[ResolvedChannel]:
        """Raise `ChannelResolutionError` when `ref` cannot be resolved."""
        ...

    def is_connected(self) -> bool: ...
