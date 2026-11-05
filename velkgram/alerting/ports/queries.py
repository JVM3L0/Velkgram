"""Read-side port used by reporting and the web."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from velkgram.alerting.domain.models import Alert, SuppressionRule


@dataclass(frozen=True, slots=True)
class DailyAlerts:
    day: date  # UTC date of `created_at`
    channel_id: int
    alerts: int
    failures: int  # failed or expired


@dataclass(frozen=True, slots=True)
class DailySuppressions:
    day: date  # UTC date of `created_at`
    channel_id: int
    rule: SuppressionRule
    count: int


@dataclass(frozen=True, slots=True)
class LatencySample:
    day: date  # UTC date of `created_at`
    channel_id: int
    telegram_ms: int
    internal_ms: int


class AlertQueries(Protocol):
    def history(self, limit: int, offset: int) -> list[Alert]:
        """Newest first."""
        ...

    def recent_failures(self, limit: int) -> list[Alert]:
        """`failed` or `expired` alerts, newest first."""
        ...

    def daily_alert_counts(self, since: date, until: date) -> list[DailyAlerts]: ...

    def daily_suppressions(self, since: date, until: date) -> list[DailySuppressions]: ...

    def suppressed_messages(self, since: date, until: date) -> set[tuple[int, int]]: ...

    def latency_samples(self, since: date, until: date) -> list[LatencySample]: ...
