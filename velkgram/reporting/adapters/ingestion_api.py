"""Adapter: ingestion read queries -> reporting `MessageStats`."""

from collections.abc import Iterator
from datetime import date

from velkgram.ingestion import IngestionQueries
from velkgram.reporting.ports.stats import DailyMessageCount


class IngestionMessageStats:
    def __init__(self, queries: IngestionQueries) -> None:
        self._q = queries

    def daily_counts(self, since: date, until: date) -> list[DailyMessageCount]:
        return [
            DailyMessageCount(c.day, c.channel_id, c.count)
            for c in self._q.daily_message_counts(since, until)
        ]

    def texts(self, since: date, until: date) -> Iterator[tuple[date, int, int, str]]:
        for m in self._q.texts_between(since, until):
            yield m.day, m.channel_id, m.message_id, m.text
