"""SQLite read queries for reporting and the web."""

import sqlite3
from collections.abc import Iterator, Sequence
from datetime import date, datetime

from velkgram.ingestion.adapters.sqlite.repository import from_iso, read_heartbeat
from velkgram.ingestion.domain.models import Heartbeat
from velkgram.ingestion.ports.queries import DailyCount, MessageText


class SqliteIngestionQueries:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def daily_message_counts(self, since: date, until: date) -> list[DailyCount]:
        rows = self._conn.execute(
            "SELECT substr(date, 1, 10) AS day, channel_id, COUNT(*) AS n FROM messages "
            "WHERE substr(date, 1, 10) BETWEEN ? AND ? GROUP BY day, channel_id "
            "ORDER BY day, channel_id",
            (since.isoformat(), until.isoformat()),
        ).fetchall()
        return [
            DailyCount(date.fromisoformat(r["day"]), int(r["channel_id"]), int(r["n"]))
            for r in rows
        ]

    def texts_between(self, since: date, until: date) -> Iterator[MessageText]:
        rows = self._conn.execute(
            "SELECT substr(date, 1, 10) AS day, channel_id, message_id, text FROM messages "
            "WHERE substr(date, 1, 10) BETWEEN ? AND ? ORDER BY day, channel_id, message_id",
            (since.isoformat(), until.isoformat()),
        )
        for r in rows:
            yield MessageText(
                date.fromisoformat(r["day"]),
                int(r["channel_id"]),
                int(r["message_id"]),
                str(r["text"]),
            )

    def heartbeat(self) -> Heartbeat | None:
        return read_heartbeat(self._conn)

    def last_message_at(self, channel_ids: Sequence[int]) -> dict[int, datetime]:
        if not channel_ids:
            return {}
        marks = ",".join("?" * len(channel_ids))
        rows = self._conn.execute(
            f"SELECT channel_id, MAX(date) AS last FROM messages "
            f"WHERE channel_id IN ({marks}) GROUP BY channel_id",
            tuple(channel_ids),
        ).fetchall()
        return {int(r["channel_id"]): from_iso(r["last"]) for r in rows}
