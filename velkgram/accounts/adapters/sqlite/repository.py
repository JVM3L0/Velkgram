"""SQLite user repository. Every write is its own short transaction."""

import sqlite3
from datetime import UTC, datetime

from velkgram.accounts.domain.models import Role, User
from velkgram.shared.db import transaction


def _to_user(row: sqlite3.Row) -> User:
    return User(
        id=int(row["id"]),
        username=row["username"],
        password_hash=row["password_hash"],
        role=Role(row["role"]),
        telegram_chat_id=row["telegram_chat_id"],
        enabled=bool(row["enabled"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class SqliteUserRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, u: User) -> User:
        try:
            with transaction(self._conn):
                cursor = self._conn.execute(
                    "INSERT INTO users (username, password_hash, role, telegram_chat_id, "
                    "enabled, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        u.username,
                        u.password_hash,
                        u.role.value,
                        u.telegram_chat_id,
                        int(u.enabled),
                        u.created_at.astimezone(UTC).isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as e:
            raise ValueError("username already exists") from e
        stored = self.get(cursor.lastrowid or 0)
        assert stored is not None
        return stored

    def update(self, u: User) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE users SET password_hash = ?, role = ?, telegram_chat_id = ?, enabled = ? "
                "WHERE id = ?",
                (u.password_hash, u.role.value, u.telegram_chat_id, int(u.enabled), u.id),
            )

    def get(self, id: int) -> User | None:
        row = self._conn.execute("SELECT * FROM users WHERE id = ?", (id,)).fetchone()
        return _to_user(row) if row is not None else None

    def get_by_username(self, username: str) -> User | None:
        row = self._conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return _to_user(row) if row is not None else None

    def list_all(self) -> list[User]:
        rows = self._conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [_to_user(r) for r in rows]
