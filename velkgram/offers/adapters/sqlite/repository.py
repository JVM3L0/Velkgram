"""SQLite offer repository. Datetimes are stored as UTC ISO-8601 strings."""

import json
import sqlite3
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

from velkgram.offers.domain.dominant import dominant_from_counts
from velkgram.offers.domain.models import (
    CouponTier,
    MatchSource,
    Offer,
    OfferKind,
    OfferMatch,
    OfferText,
    RetroRun,
    RetroStatus,
)
from velkgram.offers.domain.urls import real_product_url
from velkgram.shared.db import transaction

_MIN_INT = -(2**63)

# A match whose link has a product key different from the dominant (store, product_id) given as
# the two bound parameters. Needs `product_links pl` joined; unkeyed matches are never "other".
OTHER_PRODUCT_SQL = (
    "(pl.store IS NOT NULL AND pl.product_id IS NOT NULL AND (pl.store <> ? OR pl.product_id <> ?))"
)


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _opt_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def encode_tiers(tiers: Sequence[CouponTier]) -> str | None:
    return (
        json.dumps([[t.discount, t.min_cents, t.cap_cents, list(t.codes)] for t in tiers])
        if tiers
        else None
    )


def decode_tiers(raw: str | None) -> tuple[CouponTier, ...]:
    if not raw:
        return ()
    return tuple(
        CouponTier(str(d), _opt_int(m), _opt_int(cap), tuple(codes))
        for d, m, cap, codes in json.loads(raw)
    )


def to_offer(row: sqlite3.Row) -> Offer:
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
        comparable=bool(row["comparable"]),
        kind=OfferKind(row["kind"]),
        coupons=tuple(json.loads(row["coupons"])) if row["coupons"] else (),
        coupon_discount=row["coupon_discount"],
        coupon_min_cents=_opt_int(row["coupon_min_cents"]),
        coupon_scope=row["coupon_scope"],
        redeem_link=row["redeem_link"],
        cart_link=row["cart_link"],
        coupon_tiers=decode_tiers(row["coupon_tiers"]),
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
    "deleted, updated_at, comparable, kind, coupons, coupon_discount, coupon_min_cents, "
    "coupon_scope, redeem_link, cart_link, coupon_tiers) VALUES "
    "(?, ?, ?, ?, ?, COALESCE(?, (SELECT pl.store FROM product_links pl WHERE pl.url = ?)), "
    "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(channel_id, message_id) DO UPDATE SET "
    "posted_at = excluded.posted_at, title = excluded.title, "
    "price_cents = excluded.price_cents, store = excluded.store, "
    "main_link = excluded.main_link, has_photo = excluded.has_photo, text = excluded.text, "
    "norm_text = excluded.norm_text, origin_channel_id = excluded.origin_channel_id, "
    "origin_message_id = excluded.origin_message_id, sold_out = excluded.sold_out, "
    "deleted = excluded.deleted, updated_at = excluded.updated_at, "
    "comparable = excluded.comparable, kind = excluded.kind, coupons = excluded.coupons, "
    "coupon_discount = excluded.coupon_discount, "
    "coupon_min_cents = excluded.coupon_min_cents, coupon_scope = excluded.coupon_scope, "
    "redeem_link = excluded.redeem_link, cart_link = excluded.cart_link, "
    "coupon_tiers = excluded.coupon_tiers"
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
            o.main_link,  # bound twice: the store fallback looks the link up
            o.main_link,
            int(o.has_photo),
            o.text,
            o.norm_text,
            o.origin_channel_id,
            o.origin_message_id,
            int(o.sold_out),
            int(o.deleted),
            to_iso(o.updated_at),
            int(o.comparable),
            OfferKind(o.kind).value,
            json.dumps(list(o.coupons)) if o.coupons else None,
            o.coupon_discount,
            o.coupon_min_cents,
            o.coupon_scope,
            o.redeem_link,
            o.cart_link,
            encode_tiers(o.coupon_tiers),
        )
        with transaction(self._conn) as c:
            c.execute(_UPSERT, params)

    def get(self, channel_id: int, message_id: int) -> Offer | None:
        row = self._conn.execute(
            "SELECT * FROM offers WHERE channel_id = ? AND message_id = ?",
            (channel_id, message_id),
        ).fetchone()
        return to_offer(row) if row is not None else None

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

    def priced_points(
        self, wish_id: int, dominant: tuple[str, str] | None = None
    ) -> list[tuple[datetime, int | None]]:
        other = "0" if dominant is None else OTHER_PRODUCT_SQL
        rows = self._conn.execute(
            "SELECT m.posted_at, CASE WHEN COALESCE(o.comparable, 1) = 1 "
            f"AND NOT ({other}) THEN m.price_cents END AS price_cents "
            "FROM offer_matches m LEFT JOIN offers o "
            "ON o.channel_id = m.channel_id AND o.message_id = m.message_id "
            "LEFT JOIN product_links pl ON pl.url = o.main_link "
            "WHERE m.wish_id = ? ORDER BY m.posted_at, m.channel_id, m.message_id",
            (*(dominant or ()), wish_id),
        ).fetchall()
        return [(from_iso(r["posted_at"]), _opt_int(r["price_cents"])) for r in rows]

    def dominant_key(self, wish_id: int) -> tuple[str, str] | None:
        return self.dominant_keys([wish_id])[wish_id]

    def dominant_keys(self, wish_ids: Sequence[int]) -> dict[int, tuple[str, str] | None]:
        """Dominant (store, product_id) per wish, from one GROUP BY over their matches."""
        counts: dict[int, list[tuple[tuple[str, str], int]]] = {w: [] for w in wish_ids}
        if wish_ids:
            rows = self._conn.execute(
                "SELECT m.wish_id AS wish_id, pl.store AS store, pl.product_id AS pid, "
                "COUNT(*) AS n FROM offer_matches m JOIN offers o "
                "ON o.channel_id = m.channel_id AND o.message_id = m.message_id "
                "JOIN product_links pl ON pl.url = o.main_link "
                f"WHERE m.wish_id IN ({', '.join('?' * len(wish_ids))}) "
                "AND m.price_cents IS NOT NULL AND o.comparable = 1 "
                "AND pl.store IS NOT NULL AND pl.product_id IS NOT NULL "
                "GROUP BY m.wish_id, pl.store, pl.product_id",
                tuple(wish_ids),
            ).fetchall()
            for r in rows:
                counts[int(r["wish_id"])].append(((str(r["store"]), str(r["pid"])), int(r["n"])))
        return {w: dominant_from_counts(c, sum(n for _, n in c)) for w, c in counts.items()}

    def recent_store_offers(self, store: str, since: datetime, limit: int = 500) -> list[Offer]:
        rows = self._conn.execute(
            "SELECT * FROM offers WHERE store = ? AND kind = 'product' AND posted_at >= ? "
            "AND price_cents IS NOT NULL AND deleted = 0 AND sold_out = 0 "
            "ORDER BY posted_at DESC, channel_id DESC, message_id DESC LIMIT ?",
            (store, to_iso(since), limit),
        ).fetchall()
        return [to_offer(r) for r in rows]

    def product_urls(self, main_links: Sequence[str]) -> dict[str, str]:
        if not main_links:
            return {}
        rows = self._conn.execute(
            "SELECT url, store, product_id, kind, final_url FROM product_links "
            f"WHERE url IN ({', '.join('?' * len(main_links))})",
            tuple(main_links),
        ).fetchall()
        found: dict[str, str] = {}
        for r in rows:
            url = real_product_url(r["store"], r["product_id"], r["kind"], r["final_url"])
            if url is not None:
                found[str(r["url"])] = url
        return found

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
