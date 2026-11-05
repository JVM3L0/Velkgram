"""Read-side port used by reporting and the web."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from velkgram.ingestion.domain.models import Heartbeat
from velkgram.shared.events import MessageData


@dataclass(frozen=True, slots=True)
class DailyCount:
    day: date  # UTC date of the message `date`
    channel_id: int
    count: int


@dataclass(frozen=True, slots=True)
class MessageText:
    day: date  # UTC date of the message `date`
    channel_id: int
    message_id: int
    text: str


@dataclass(frozen=True, slots=True)
class StoredMessage:
    """A stored message with its latest text and the flags derived from its history."""

    message: MessageData
    deleted: bool
    sold_out: bool


class IngestionQueries(Protocol):
    def daily_message_counts(self, since: date, until: date) -> list[DailyCount]: ...

    def texts_between(self, since: date, until: date) -> Iterator[MessageText]: ...

    def heartbeat(self) -> Heartbeat | None: ...

    def last_message_at(self, channel_ids: Sequence[int]) -> dict[int, datetime]: ...

    def iter_stored_messages(self, batch_size: int = 1000) -> Iterator[StoredMessage]:
        """Every message ordered by (date, channel_id, message_id), with its latest text."""
        ...
