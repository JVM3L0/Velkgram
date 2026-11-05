"""SQLite read queries for reporting and the web."""

import sqlite3
from collections.abc import Iterator, Sequence
from datetime import date, datetime

from velkgram.ingestion.adapters.sqlite.repository import from_iso, read_heartbeat, to_message
from velkgram.ingestion.domain.models import Heartbeat
from velkgram.ingestion.ports.queries import DailyCount, MessageText, StoredMessage

_STORED_SQL = (
    "SELECT m.channel_id, m.message_id, m.date, m.received_at, "
    "COALESCE(v.text, m.text) AS text, COALESCE(v.links, m.links) AS links, "
    "m.fwd_from_channel_id, m.fwd_from_message_id, m.grouped_id, m.has_photo, m.source, "
    "m.deleted_at IS NOT NULL AS deleted, "
    "EXISTS (SELECT 1 FROM message_versions s WHERE s.channel_id = m.channel_id "
    "AND s.message_id = m.message_id AND s.sold_out_hint = 1) AS sold_out "
    "FROM messages m LEFT JOIN message_versions v ON v.channel_id = m.channel_id "
    "AND v.message_id = m.message_id AND v.version = (SELECT MAX(version) "
    "FROM message_versions x WHERE x.channel_id = m.channel_id AND x.message_id = m.message_id) "
    "WHERE (m.date, m.channel_id, m.message_id) > (?, ?, ?) "
    "ORDER BY m.date, m.channel_id, m.message_id LIMIT ?"
)


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

    def iter_stored_messages(self, batch_size: int = 1000) -> Iterator[StoredMessage]:
        after: tuple[str, int, int] = ("", -(2**63), -(2**63))
        while True:
            rows = self._conn.execute(_STORED_SQL, (*after, batch_size)).fetchall()
            for r in rows:
                yield StoredMessage(to_message(r), bool(r["deleted"]), bool(r["sold_out"]))
            if len(rows) < batch_size:
                return
            last = rows[-1]
            after = (last["date"], int(last["channel_id"]), int(last["message_id"]))
