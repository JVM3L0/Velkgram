"""SQLite offer repository. Datetimes are stored as UTC ISO-8601 strings."""

import sqlite3
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

from velkgram.offers.domain.models import (
    MatchSource,
    Offer,
    OfferMatch,
    OfferText,
    RetroRun,
    RetroStatus,
)
from velkgram.shared.db import transaction

_MIN_INT = -(2**63)


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _opt_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def _to_offer(row: sqlite3.Row) -> Offer:
    return Offer(
        channel_id=int(row["channel_id"]),
        message_id=int(row["message_id"]),
        posted_at=from_iso(row["posted_at"]),
        title=str(row["title"]),
        price_cents=_opt_int(row["price_cents"]),
        store=row["store"],
        main_link=row["main_link"],
        has_photo=bool(row["has_photo"]),
        text=row["text"],
        norm_text=row["norm_text"],
        origin_channel_id=_opt_int(row["origin_channel_id"]),
        origin_message_id=_opt_int(row["origin_message_id"]),
        sold_out=bool(row["sold_out"]),
        deleted=bool(row["deleted"]),
        updated_at=from_iso(row["updated_at"]),
    )


def _to_run(row: sqlite3.Row) -> RetroRun:
    return RetroRun(
        wish_id=int(row["wish_id"]),
        fingerprint=str(row["fingerprint"]),
        status=RetroStatus(row["status"]),
        started_at=from_iso(row["started_at"]),
        finished_at=from_iso(row["finished_at"]) if row["finished_at"] is not None else None,
        error=row["error"],
    )


def _match_params(m: OfferMatch) -> tuple[object, ...]:
    return (
        m.wish_id,
        m.channel_id,
        m.message_id,
        m.price_cents,
        to_iso(m.posted_at),
        MatchSource(m.source).value,
        to_iso(m.matched_at),
    )


_INSERT_MATCH = (
    "INSERT OR IGNORE INTO offer_matches "
    "(wish_id, channel_id, message_id, price_cents, posted_at, source, matched_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)

_UPSERT = (
    "INSERT INTO offers (channel_id, message_id, posted_at, title, price_cents, store, "
    "main_link, has_photo, text, norm_text, origin_channel_id, origin_message_id, sold_out, "
    "deleted, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(channel_id, message_id) DO UPDATE SET "
    "posted_at = excluded.posted_at, title = excluded.title, "
    "price_cents = excluded.price_cents, store = excluded.store, "
    "main_link = excluded.main_link, has_photo = excluded.has_photo, text = excluded.text, "
    "norm_text = excluded.norm_text, origin_channel_id = excluded.origin_channel_id, "
    "origin_message_id = excluded.origin_message_id, sold_out = excluded.sold_out, "
    "deleted = excluded.deleted, updated_at = excluded.updated_at"
)


class SqliteOfferRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, o: Offer) -> None:
        params = (
            o.channel_id,
            o.message_id,
            to_iso(o.posted_at),
            o.title,
            o.price_cents,
            o.store,
            o.main_link,
            int(o.has_photo),
            o.text,
            o.norm_text,
            o.origin_channel_id,
            o.origin_message_id,
            int(o.sold_out),
            int(o.deleted),
            to_iso(o.updated_at),
        )
        with transaction(self._conn) as c:
            c.execute(_UPSERT, params)

    def get(self, channel_id: int, message_id: int) -> Offer | None:
        row = self._conn.execute(
            "SELECT * FROM offers WHERE channel_id = ? AND message_id = ?",
            (channel_id, message_id),
        ).fetchone()
        return _to_offer(row) if row is not None else None

    def mark_deleted(self, channel_id: int, message_ids: Sequence[int], at: datetime) -> None:
        if not message_ids:
            return
        with transaction(self._conn) as c:
            c.executemany(
                "UPDATE offers SET deleted = 1, updated_at = ? "
                "WHERE channel_id = ? AND message_id = ?",
                [(to_iso(at), channel_id, mid) for mid in message_ids],
            )

    def add_match(self, m: OfferMatch) -> bool:
        with transaction(self._conn) as c:
            return c.execute(_INSERT_MATCH, _match_params(m)).rowcount == 1

    def add_matches(self, ms: Sequence[OfferMatch]) -> int:
        if not ms:
            return 0
        with transaction(self._conn) as c:
            before = c.total_changes
            c.executemany(_INSERT_MATCH, [_match_params(m) for m in ms])
            return c.total_changes - before

    def delete_matches(self, wish_id: int, since: datetime | None) -> int:
        with transaction(self._conn) as c:
            if since is None:
                cur = c.execute("DELETE FROM offer_matches WHERE wish_id = ?", (wish_id,))
            else:
                cur = c.execute(
                    "DELETE FROM offer_matches WHERE wish_id = ? AND posted_at >= ?",
                    (wish_id, to_iso(since)),
                )
            return cur.rowcount

    def iter_offers_with_text(self, since: datetime, batch_size: int) -> Iterator[list[OfferText]]:
        cursor: tuple[str, int, int] = (to_iso(since), _MIN_INT, _MIN_INT)
        # A fresh keyset query per batch: no read cursor stays open while the caller awaits.
        while True:
            rows = self._conn.execute(
                "SELECT channel_id, message_id, posted_at, price_cents, norm_text FROM offers "
                "WHERE norm_text IS NOT NULL AND deleted = 0 "
                "AND (posted_at, channel_id, message_id) > (?, ?, ?) "
                "ORDER BY posted_at, channel_id, message_id LIMIT ?",
                (*cursor, batch_size),
            ).fetchall()
            if not rows:
                return
            yield [
                OfferText(
                    int(r["channel_id"]),
                    int(r["message_id"]),
                    from_iso(r["posted_at"]),
                    _opt_int(r["price_cents"]),
                    str(r["norm_text"]),
                )
                for r in rows
            ]
            last = rows[-1]
            cursor = (str(last["posted_at"]), int(last["channel_id"]), int(last["message_id"]))
            if len(rows) < batch_size:
                return

    def priced_points(self, wish_id: int) -> list[tuple[datetime, int | None]]:
        rows = self._conn.execute(
            "SELECT posted_at, price_cents FROM offer_matches WHERE wish_id = ? "
            "ORDER BY posted_at, channel_id, message_id",
            (wish_id,),
        ).fetchall()
        return [(from_iso(r["posted_at"]), _opt_int(r["price_cents"])) for r in rows]

    def purge_text_before(self, cutoff: datetime) -> int:
        with transaction(self._conn) as c:
            cur = c.execute(
                "UPDATE offers SET text = NULL, norm_text = NULL "
                "WHERE posted_at < ? AND text IS NOT NULL",
                (to_iso(cutoff),),
            )
            return cur.rowcount

    def get_retro_run(self, wish_id: int) -> RetroRun | None:
        row = self._conn.execute(
            "SELECT * FROM retro_runs WHERE wish_id = ?", (wish_id,)
        ).fetchone()
        return _to_run(row) if row is not None else None

    def save_retro_run(self, r: RetroRun) -> None:
        with transaction(self._conn) as c:
            c.execute(
                "INSERT INTO retro_runs (wish_id, fingerprint, status, started_at, finished_at, "
                "error) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(wish_id) DO UPDATE SET "
                "fingerprint = excluded.fingerprint, status = excluded.status, "
                "started_at = excluded.started_at, finished_at = excluded.finished_at, "
                "error = excluded.error",
                (
                    r.wish_id,
                    r.fingerprint,
                    RetroStatus(r.status).value,
                    to_iso(r.started_at),
                    to_iso(r.finished_at) if r.finished_at is not None else None,
                    r.error,
                ),
            )

    def list_retro_runs(self) -> list[RetroRun]:
        rows = self._conn.execute("SELECT * FROM retro_runs ORDER BY wish_id").fetchall()
        return [_to_run(r) for r in rows]

    def delete_wish_data(self, wish_id: int) -> None:
        with transaction(self._conn) as c:
            c.execute("DELETE FROM offer_matches WHERE wish_id = ?", (wish_id,))
            c.execute("DELETE FROM retro_runs WHERE wish_id = ?", (wish_id,))

    def delete_retro_run(self, wish_id: int) -> None:
        with transaction(self._conn) as c:
            c.execute("DELETE FROM retro_runs WHERE wish_id = ?", (wish_id,))
