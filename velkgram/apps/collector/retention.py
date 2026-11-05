"""Once-per-local-day schedule for the text retention purge (in-memory state)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo


class RetentionSchedule:
    def __init__(self, tz: ZoneInfo, hour: int = 4) -> None:
        self._tz = tz
        self._hour = hour
        self._last_run: date | None = None

    def due(self, now: datetime) -> bool:
        local = now.astimezone(self._tz)
        return local.hour >= self._hour and local.date() != self._last_run

    def mark_ran(self, now: datetime) -> None:
        self._last_run = now.astimezone(self._tz).date()
