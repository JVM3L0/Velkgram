"""SQLite channel repository. Timestamps are stored as UTC ISO-8601."""

import sqlite3
from datetime import UTC, datetime

from velkgram.channels.domain.models import Channel, ChannelStatus
from velkgram.shared.db import bump_version, transaction

_COLUMNS = "id, ref, telegram_id, name, status, error, enabled, silent_after_hours, created_at"


def _to_channel(row: sqlite3.Row) -> Channel:
    return Channel(
        id=int(row["id"]),
        ref=str(row["ref"]),
        telegram_id=None if row["telegram_id"] is None else int(row["telegram_id"]),
        name=row["name"],
        status=ChannelStatus(row["status"]),
        error=row["error"],
        enabled=bool(row["enabled"]),
        silent_after_hours=int(row["silent_after_hours"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class SqliteChannelRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, c: Channel) -> Channel:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "INSERT INTO channels (ref, telegram_id, name, status, error, enabled, "
                "silent_after_hours, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    c.ref,
                    c.telegram_id,
                    c.name,
                    c.status.value,
                    c.error,
                    int(c.enabled),
                    c.silent_after_hours,
                    c.created_at.astimezone(UTC).isoformat(),
                ),
            )
            bump_version(self._conn, "channels")
        stored = self.get(cursor.lastrowid or 0)
        assert stored is not None
        return stored

    def update(self, c: Channel) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE channels SET ref = ?, telegram_id = ?, name = ?, status = ?, error = ?, "
                "enabled = ?, silent_after_hours = ? WHERE id = ?",
                (
                    c.ref,
                    c.telegram_id,
                    c.name,
                    c.status.value,
                    c.error,
                    int(c.enabled),
                    c.silent_after_hours,
                    c.id,
                ),
            )
            bump_version(self._conn, "channels")

    def delete(self, id: int) -> None:
        with transaction(self._conn):
            self._conn.execute("DELETE FROM channels WHERE id = ?", (id,))
            bump_version(self._conn, "channels")

    def get(self, id: int) -> Channel | None:
        return self._one("WHERE id = ?", (id,))

    def get_by_ref(self, ref: str) -> Channel | None:
        return self._one("WHERE ref = ?", (ref,))

    def list_all(self) -> list[Channel]:
        return self._many("")

    def list_enabled_active(self) -> list[Channel]:
        return self._many("WHERE enabled = 1 AND status = 'active'")

    def list_pending(self) -> list[Channel]:
        return self._many("WHERE status = 'pending'")

    def _one(self, where: str, params: tuple[object, ...]) -> Channel | None:
        row = self._conn.execute(f"SELECT {_COLUMNS} FROM channels {where}", params).fetchone()
        return _to_channel(row) if row else None

    def _many(self, where: str) -> list[Channel]:
        rows = self._conn.execute(f"SELECT {_COLUMNS} FROM channels {where} ORDER BY id").fetchall()
        return [_to_channel(r) for r in rows]
