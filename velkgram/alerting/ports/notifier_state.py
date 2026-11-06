"""Delivery state of the alert notifier (alerting-owned data)."""

from datetime import datetime
from enum import StrEnum
from typing import Protocol


class NotifierStatus(StrEnum):
    OK = "ok"
    NEEDS_START = "needs_start"
    ERROR = "error"
    DISABLED = "disabled"


class NotifierStateStore(Protocol):
    def set(self, status: NotifierStatus, detail: str | None, at: datetime) -> None:
        """Write only when the status or the detail changed; never touches chat_id."""
        ...

    def get(self) -> tuple[NotifierStatus, str | None, datetime] | None: ...

    def set_chat_id(self, chat_id: int) -> None:
        """Update only chat_id; a no-op when there is no row yet."""
        ...

    def get_chat_id(self) -> int | None: ...
