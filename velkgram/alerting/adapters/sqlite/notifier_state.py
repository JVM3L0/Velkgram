"""SQLite notifier state store (single row, id = 1)."""

import sqlite3
from datetime import datetime

from velkgram.alerting.adapters.sqlite.repository import from_iso, to_iso
from velkgram.alerting.ports.notifier_state import NotifierStatus
from velkgram.shared.db import transaction


class SqliteNotifierStateStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def set(self, status: NotifierStatus, detail: str | None, at: datetime) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO notifier_state (id, status, detail, updated_at) VALUES (1, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET status = excluded.status, detail = excluded.detail, "
                "updated_at = excluded.updated_at "
                "WHERE status IS NOT excluded.status OR detail IS NOT excluded.detail",
                (str(status), detail, to_iso(at)),
            )

    def get(self) -> tuple[NotifierStatus, str | None, datetime] | None:
        row = self._conn.execute(
            "SELECT status, detail, updated_at FROM notifier_state WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        detail = None if row["detail"] is None else str(row["detail"])
        return NotifierStatus(row["status"]), detail, from_iso(str(row["updated_at"]))

    def set_chat_id(self, chat_id: int) -> None:
        with transaction(self._conn):
            self._conn.execute("UPDATE notifier_state SET chat_id = ? WHERE id = 1", (chat_id,))

    def get_chat_id(self) -> int | None:
        row = self._conn.execute("SELECT chat_id FROM notifier_state WHERE id = 1").fetchone()
        return None if row is None or row["chat_id"] is None else int(row["chat_id"])
