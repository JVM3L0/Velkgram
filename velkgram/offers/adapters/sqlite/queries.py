"""SQLite read queries for the offers feed, product history and summaries."""

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from velkgram.offers.adapters.sqlite.repository import (
    SqliteOfferRepository,
    from_iso,
    to_iso,
)
from velkgram.offers.domain.models import MatchSource
from velkgram.offers.domain.stats import product_stats
from velkgram.offers.ports.queries import (
    FeedCursor,
    FeedFilter,
    FeedPage,
    MatchCard,
    OfferCard,
    PricePoint,
    ProductHistory,
    WishSummary,
)

_MIN_DAYS_FOR_DAILY = 3  # fewer distinct days: plot every priced match
_MAX_POINTS = 200
_RECENT = 30

_CARD_COLUMNS = (
    "o.channel_id, o.message_id, o.posted_at, o.title, o.price_cents, o.store, o.main_link, "
    "o.has_photo, o.sold_out, o.deleted, "
    "(SELECT COUNT(*) FROM offers r WHERE r.origin_channel_id = o.channel_id "
    "AND r.origin_message_id = o.message_id) AS repost_count"
)


def fts_query(q: str) -> str | None:
    """Quote every token (no FTS syntax from the user) and prefix-match the last one."""
    tokens = [t for t in q.split() if any(ch.isalnum() for ch in t)]
    if not tokens:
        return None
    quoted = ['"' + t.replace('"', '""') + '"' for t in tokens]
    quoted[-1] += "*"
    return " ".join(quoted)


def _card(row: sqlite3.Row) -> OfferCard:
    return OfferCard(
        channel_id=int(row["channel_id"]),
        message_id=int(row["message_id"]),
        posted_at=from_iso(row["posted_at"]),
        title=str(row["title"]),
        price_cents=None if row["price_cents"] is None else int(row["price_cents"]),
        store=row["store"],
        main_link=row["main_link"],
        has_photo=bool(row["has_photo"]),
        sold_out=bool(row["sold_out"]),
        deleted=bool(row["deleted"]),
        repost_count=int(row["repost_count"]),
    )


def _cursor_of(card: OfferCard) -> FeedCursor:
    return FeedCursor(card.posted_at, card.channel_id, card.message_id)


class SqliteOfferQueries:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._repo = SqliteOfferRepository(conn)

    def feed(self, f: FeedFilter, cursor: FeedCursor | None, limit: int = 30) -> FeedPage:
        where = [
            "NOT (o.origin_channel_id IS NOT NULL AND EXISTS ("
            "SELECT 1 FROM offers x WHERE x.channel_id = o.origin_channel_id "
            "AND x.message_id = o.origin_message_id))"
        ]
        params: list[object] = []
        match = fts_query(f.q) if f.q is not None else None
        if match is not None:
            where.append("o.id IN (SELECT rowid FROM offers_fts WHERE offers_fts MATCH ?)")
            params.append(match)
        if f.min_cents is not None:
            where.append("o.price_cents >= ?")
            params.append(f.min_cents)
        if f.max_cents is not None:
            where.append("o.price_cents <= ?")
            params.append(f.max_cents)
        if f.stores:
            where.append(f"o.store IN ({', '.join('?' * len(f.stores))})")
            params.extend(f.stores)
        if f.priced_only:
            where.append("o.price_cents IS NOT NULL")
        if f.channel_id is not None:
            where.append("o.channel_id = ?")
            params.append(f.channel_id)
        if cursor is not None:
            where.append("(o.posted_at, o.channel_id, o.message_id) < (?, ?, ?)")
            params.extend((to_iso(cursor.posted_at), cursor.channel_id, cursor.message_id))
        rows = self._conn.execute(
            f"SELECT {_CARD_COLUMNS} FROM offers o WHERE {' AND '.join(where)} "
            "ORDER BY o.posted_at DESC, o.channel_id DESC, o.message_id DESC LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
        cards = tuple(_card(r) for r in rows[:limit])
        more = len(rows) > limit
        return FeedPage(cards, _cursor_of(cards[-1]) if more and cards else None)

    def product(
        self,
        wish_id: int,
        now: datetime,
        range_days: int | None,
        cursor: FeedCursor | None,
        limit: int = 30,
    ) -> ProductHistory:
        stats = product_stats(self._repo.priced_points(wish_id), now)
        since = None if range_days is None else to_iso(now - timedelta(days=range_days))
        matches, next_cursor = self._matches_page(wish_id, cursor, limit)
        return ProductHistory(
            stats=stats,
            points=self._points(wish_id, since),
            matches=matches,
            next_cursor=next_cursor,
            retro=self._repo.get_retro_run(wish_id),
        )

    def _points(self, wish_id: int, since: str | None) -> tuple[PricePoint, ...]:
        where = "wish_id = ? AND price_cents IS NOT NULL"
        params: list[object] = [wish_id]
        if since is not None:
            where += " AND posted_at >= ?"
            params.append(since)
        distinct_days = self._conn.execute(
            f"SELECT COUNT(DISTINCT substr(posted_at, 1, 10)) FROM offer_matches WHERE {where}",
            params,
        ).fetchone()[0]
        if distinct_days < _MIN_DAYS_FOR_DAILY:
            rows = self._conn.execute(
                f"SELECT posted_at, price_cents FROM offer_matches WHERE {where} "
                "ORDER BY posted_at, channel_id, message_id",
                params,
            ).fetchall()
            return tuple(
                PricePoint(datetime.fromisoformat(r["posted_at"]), int(r["price_cents"]))
                for r in rows
            )
        rows = self._conn.execute(
            "SELECT substr(posted_at, 1, 10) AS day, MIN(price_cents) AS low FROM offer_matches "
            f"WHERE {where} GROUP BY day ORDER BY day",
            params,
        ).fetchall()
        days = [(datetime.fromisoformat(r["day"]).replace(tzinfo=UTC), int(r["low"])) for r in rows]
        if len(days) > _MAX_POINTS:
            n = len(days)
            buckets = [
                days[i * n // _MAX_POINTS : (i + 1) * n // _MAX_POINTS] for i in range(_MAX_POINTS)
            ]
            days = [(b[-1][0], min(p for _, p in b)) for b in buckets]
        return tuple(PricePoint(d, p) for d, p in days)

    def _matches_page(
        self, wish_id: int, cursor: FeedCursor | None, limit: int
    ) -> tuple[tuple[MatchCard, ...], FeedCursor | None]:
        where = "m.wish_id = ?"
        params: list[object] = [wish_id]
        if cursor is not None:
            where += " AND (m.posted_at, m.channel_id, m.message_id) < (?, ?, ?)"
            params.extend((to_iso(cursor.posted_at), cursor.channel_id, cursor.message_id))
        rows = self._conn.execute(
            f"SELECT {_CARD_COLUMNS}, m.source AS source, m.price_cents AS matched_price "
            "FROM offer_matches m JOIN offers o "
            "ON o.channel_id = m.channel_id AND o.message_id = m.message_id "
            f"WHERE {where} ORDER BY m.posted_at DESC, m.channel_id DESC, m.message_id DESC "
            "LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
        page = rows[:limit]
        cards = tuple(
            MatchCard(
                _card(r),
                MatchSource(r["source"]),
                None if r["matched_price"] is None else int(r["matched_price"]),
            )
            for r in page
        )
        more = len(rows) > limit and bool(cards)
        return cards, (_cursor_of(cards[-1].card) if more else None)

    def summaries(self, wish_ids: Sequence[int]) -> dict[int, WishSummary]:
        out: dict[int, WishSummary] = {}
        for wid in wish_ids:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM offer_matches WHERE wish_id = ?", (wid,)
            ).fetchone()[0]
            rows = self._conn.execute(
                "SELECT price_cents FROM offer_matches WHERE wish_id = ? "
                "AND price_cents IS NOT NULL "
                "ORDER BY posted_at DESC, channel_id DESC, message_id DESC LIMIT ?",
                (wid, _RECENT),
            ).fetchall()
            recent = tuple(int(r[0]) for r in reversed(rows))
            out[wid] = WishSummary(recent[-1] if recent else None, int(count), recent)
        return out

    def stores_seen(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT store FROM offers WHERE store IS NOT NULL ORDER BY store"
        ).fetchall()
        return [str(r[0]) for r in rows]
