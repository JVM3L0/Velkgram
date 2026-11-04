"""SQLite message repository. Datetimes are stored as UTC ISO-8601 strings."""

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal, cast

from velkgram.ingestion.domain.models import ConnectionState, Heartbeat
from velkgram.shared.db import transaction
from velkgram.shared.events import MessageData

_COLUMNS = (
    "channel_id, message_id, date, received_at, text, links, fwd_from_channel_id, "
    "fwd_from_message_id, grouped_id, has_photo, source"
)


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _opt_int(value: object) -> int | None:
    return None if value is None else int(cast(int, value))


def _to_message(row: sqlite3.Row) -> MessageData:
    return MessageData(
        channel_id=int(row["channel_id"]),
        message_id=int(row["message_id"]),
        date=from_iso(row["date"]),
        received_at=from_iso(row["received_at"]),
        text=str(row["text"]),
        links=tuple(json.loads(row["links"])),
        fwd_from_channel_id=_opt_int(row["fwd_from_channel_id"]),
        fwd_from_message_id=_opt_int(row["fwd_from_message_id"]),
        grouped_id=_opt_int(row["grouped_id"]),
        has_photo=bool(row["has_photo"]),
        source=cast(Literal["live", "backfill"], row["source"]),
    )


class SqliteMessageRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, m: MessageData) -> bool:
        with transaction(self._conn):
            cursor = self._conn.execute(
                f"INSERT OR IGNORE INTO messages ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    m.channel_id,
                    m.message_id,
                    to_iso(m.date),
                    to_iso(m.received_at),
                    m.text,
                    json.dumps(m.links),
                    m.fwd_from_channel_id,
                    m.fwd_from_message_id,
                    m.grouped_id,
                    int(m.has_photo),
                    m.source,
                ),
            )
        return cursor.rowcount == 1

    def add_version(self, m: MessageData, edited_at: datetime, sold_out_hint: bool) -> int:
        with transaction(self._conn):
            row = self._conn.execute(
                "INSERT INTO message_versions "
                "(channel_id, message_id, version, edited_at, text, links, sold_out_hint) "
                "SELECT ?1, ?2, COALESCE(MAX(version), 0) + 1, ?3, ?4, ?5, ?6 "
                "FROM message_versions WHERE channel_id = ?1 AND message_id = ?2 "
                "RETURNING version",
                (
                    m.channel_id,
                    m.message_id,
                    to_iso(edited_at),
                    m.text,
                    json.dumps(m.links),
                    int(sold_out_hint),
                ),
            ).fetchone()
        return int(row[0])

    def mark_deleted(self, channel_id: int, message_ids: Sequence[int], at: datetime) -> None:
        with transaction(self._conn):
            self._conn.executemany(
                "UPDATE messages SET deleted_at = ? WHERE channel_id = ? AND message_id = ?",
                [(to_iso(at), channel_id, message_id) for message_id in message_ids],
            )

    def mark_processed(self, channel_id: int, message_id: int, at: datetime) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE messages SET processed_at = ? WHERE channel_id = ? AND message_id = ?",
                (to_iso(at), channel_id, message_id),
            )

    def list_unprocessed_since(self, since: datetime) -> list[MessageData]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM messages WHERE processed_at IS NULL AND received_at >= ? "
            "ORDER BY received_at, channel_id, message_id",
            (to_iso(since),),
        ).fetchall()
        return [_to_message(r) for r in rows]

    def get(self, channel_id: int, message_id: int) -> MessageData | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM messages WHERE channel_id = ? AND message_id = ?",
            (channel_id, message_id),
        ).fetchone()
        return _to_message(row) if row else None

    def get_cursor(self, channel_id: int) -> int | None:
        row = self._conn.execute(
            "SELECT last_message_id FROM ingestion_cursors WHERE channel_id = ?", (channel_id,)
        ).fetchone()
        return int(row[0]) if row else None

    def set_cursor(self, channel_id: int, last_message_id: int) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO ingestion_cursors (channel_id, last_message_id, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(channel_id) DO UPDATE SET "
                "last_message_id = MAX(last_message_id, excluded.last_message_id), "
                "updated_at = excluded.updated_at",
                (channel_id, last_message_id, to_iso(datetime.now(UTC))),
            )

    def write_heartbeat(self, h: Heartbeat) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO collector_heartbeat "
                "(id, last_seen, connection_state, fatal_reason, messages_seen, alerts_sent) "
                "VALUES (1, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "last_seen = excluded.last_seen, connection_state = excluded.connection_state, "
                "fatal_reason = excluded.fatal_reason, messages_seen = excluded.messages_seen, "
                "alerts_sent = excluded.alerts_sent",
                (
                    to_iso(h.last_seen),
                    h.connection_state,
                    h.fatal_reason,
                    h.messages_seen,
                    h.alerts_sent,
                ),
            )

    def read_heartbeat(self) -> Heartbeat | None:
        return read_heartbeat(self._conn)


def read_heartbeat(conn: sqlite3.Connection) -> Heartbeat | None:
    row = conn.execute(
        "SELECT last_seen, connection_state, fatal_reason, messages_seen, alerts_sent "
        "FROM collector_heartbeat WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    return Heartbeat(
        last_seen=from_iso(row["last_seen"]),
        connection_state=cast(ConnectionState, row["connection_state"]),
        fatal_reason=row["fatal_reason"],
        messages_seen=int(row["messages_seen"]),
        alerts_sent=int(row["alerts_sent"]),
    )
