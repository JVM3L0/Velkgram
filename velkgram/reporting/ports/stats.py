"""Read-side ports owned by reporting (adapters convert from other modules' rows)."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

PriceExtractor = Callable[[str], int | None]


@dataclass(frozen=True, slots=True)
class DailyMessageCount:
    day: date
    channel_id: int
    count: int


@dataclass(frozen=True, slots=True)
class DailyAlertStat:
    day: date
    channel_id: int
    alerts: int
    failures: int


@dataclass(frozen=True, slots=True)
class DailySuppressionStat:
    day: date
    channel_id: int
    rule: str
    count: int


@dataclass(frozen=True, slots=True)
class LatencyStat:
    day: date
    channel_id: int
    telegram_ms: int
    internal_ms: int


class MessageStats(Protocol):
    def daily_counts(self, since: date, until: date) -> list[DailyMessageCount]: ...

    def texts(self, since: date, until: date) -> Iterable[tuple[date, int, int, str]]:
        """Yield `(day, channel_id, message_id, text)`."""
        ...


class AlertStats(Protocol):
    def daily_alerts(self, since: date, until: date) -> list[DailyAlertStat]: ...

    def daily_suppressions(self, since: date, until: date) -> list[DailySuppressionStat]: ...

    def suppressed_messages(self, since: date, until: date) -> set[tuple[int, int]]: ...

    def latency_samples(self, since: date, until: date) -> list[LatencyStat]: ...
