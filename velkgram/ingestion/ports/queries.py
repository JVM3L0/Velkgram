"""Read-side port used by reporting and the web."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from velkgram.ingestion.domain.models import Heartbeat


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


class IngestionQueries(Protocol):
    def daily_message_counts(self, since: date, until: date) -> list[DailyCount]: ...

    def texts_between(self, since: date, until: date) -> Iterator[MessageText]: ...

    def heartbeat(self) -> Heartbeat | None: ...

    def last_message_at(self, channel_ids: Sequence[int]) -> dict[int, datetime]: ...
