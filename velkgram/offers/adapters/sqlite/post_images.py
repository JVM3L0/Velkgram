"""SQLite store for post image URLs. Every write is its own short transaction."""

import sqlite3
from collections.abc import Sequence
from datetime import datetime

from velkgram.offers.adapters.sqlite.repository import to_iso
from velkgram.offers.domain.channel_page import PostImage
from velkgram.shared.db import transaction


class SqlitePostImageRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, channel_id: int, images: Sequence[PostImage], now: datetime) -> None:
        if not images:
            return
        stamp = to_iso(now)
        with transaction(self._conn) as c:
            c.executemany(
                "INSERT INTO post_images (channel_id, message_id, url, fetched_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (channel_id, message_id) "
                "DO UPDATE SET url = excluded.url, fetched_at = excluded.fetched_at",
                [(channel_id, i.message_id, i.url, stamp) for i in images],
            )

    def get(self, channel_id: int, message_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT url FROM post_images WHERE channel_id = ? AND message_id = ?",
            (channel_id, message_id),
        ).fetchone()
        return str(row["url"]) if row is not None else None

    def purge_before(self, cutoff: datetime) -> int:
        with transaction(self._conn) as c:
            return c.execute(
                "DELETE FROM post_images WHERE fetched_at < ?", (to_iso(cutoff),)
            ).rowcount
