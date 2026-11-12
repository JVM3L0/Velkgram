"""SQLite wish repository. Terms are stored as JSON arrays."""

import json
import sqlite3

from velkgram.shared.db import bump_version, transaction
from velkgram.wishlist.domain.models import Wish

_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
_COLUMNS = "id, name, required_terms, excluded_terms, max_price_cents, enabled, user_id"


def _to_wish(row: sqlite3.Row) -> Wish:
    return Wish(
        id=int(row["id"]),
        name=str(row["name"]),
        required_terms=tuple(json.loads(row["required_terms"])),
        excluded_terms=tuple(json.loads(row["excluded_terms"])),
        max_price_cents=int(row["max_price_cents"]),
        enabled=bool(row["enabled"]),
        user_id=int(row["user_id"]),
    )


class SqliteWishRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, w: Wish) -> Wish:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "INSERT INTO wishes (name, required_terms, excluded_terms, max_price_cents, "
                "enabled, user_id, created_at, updated_at) "
                f"VALUES (?, ?, ?, ?, ?, ?, {_NOW}, {_NOW})",
                (
                    w.name,
                    json.dumps(w.required_terms),
                    json.dumps(w.excluded_terms),
                    w.max_price_cents,
                    int(w.enabled),
                    w.user_id,
                ),
            )
            bump_version(self._conn, "wishlist")
        return Wish(
            cursor.lastrowid,
            w.name,
            w.required_terms,
            w.excluded_terms,
            w.max_price_cents,
            w.enabled,
            w.user_id,
        )

    def update(self, w: Wish) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE wishes SET name = ?, required_terms = ?, excluded_terms = ?, "
                f"max_price_cents = ?, enabled = ?, updated_at = {_NOW} WHERE id = ?",
                (
                    w.name,
                    json.dumps(w.required_terms),
                    json.dumps(w.excluded_terms),
                    w.max_price_cents,
                    int(w.enabled),
                    w.id,
                ),
            )
            bump_version(self._conn, "wishlist")

    def delete(self, id: int) -> None:
        with transaction(self._conn):
            self._conn.execute("DELETE FROM wishes WHERE id = ?", (id,))
            bump_version(self._conn, "wishlist")

    def get(self, id: int) -> Wish | None:
        row = self._conn.execute(f"SELECT {_COLUMNS} FROM wishes WHERE id = ?", (id,)).fetchone()
        return _to_wish(row) if row else None

    def list_all(self) -> list[Wish]:
        rows = self._conn.execute(f"SELECT {_COLUMNS} FROM wishes ORDER BY id").fetchall()
        return [_to_wish(r) for r in rows]

    def list_for_user(self, user_id: int) -> list[Wish]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM wishes WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()
        return [_to_wish(r) for r in rows]

    def list_enabled(self) -> list[Wish]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM wishes WHERE enabled = 1 ORDER BY id"
        ).fetchall()
        return [_to_wish(r) for r in rows]
