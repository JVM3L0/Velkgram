"""SQLite read queries for the offers feed, product history and summaries."""

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from velkgram.offers.adapters.sqlite.repository import (
    OTHER_PRODUCT_SQL,
    SqliteOfferRepository,
    decode_tiers,
    from_iso,
    to_iso,
    to_offer,
)
from velkgram.offers.domain.coupon_targets import applicable_tier
from velkgram.offers.domain.models import MatchSource, OfferKind
from velkgram.offers.domain.stats import product_stats
from velkgram.offers.ports.queries import (
    ActiveCouponView,
    CouponFilter,
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

_MATCH_JOIN = (
    "offer_matches m JOIN offers o ON o.channel_id = m.channel_id AND o.message_id = m.message_id"
)
_PL_JOIN = "LEFT JOIN product_links pl ON pl.url = o.main_link"
_COMPARABLE_MATCH = "m.price_cents IS NOT NULL AND o.comparable = 1"

_FEED_FROM = "offers o LEFT JOIN product_links pl ON pl.url = o.main_link"
_OFFERS_FROM = "offers o"
_COLLAPSE_DAYS = 1.0  # 24 h window of the same-product collapse (julianday is in days)


def _not_repost(outer: str, inner: str) -> str:
    return (
        f"NOT ({outer}.origin_channel_id IS NOT NULL AND EXISTS ("
        f"SELECT 1 FROM offers {inner} WHERE {inner}.channel_id = {outer}.origin_channel_id "
        f"AND {inner}.message_id = {outer}.origin_message_id))"
    )


_NOT_REPOST = _not_repost("o", "r")

# Hides `o` when a newer visible offer of the same product and price sits within 24 h.
# `pl.product_id IS NOT NULL` leads so unenriched rows short-circuit.
_NOT_SAME_PRODUCT = (
    "NOT (pl.product_id IS NOT NULL AND o.price_cents IS NOT NULL AND EXISTS ("
    "SELECT 1 FROM product_links px "
    "CROSS JOIN offers x INDEXED BY idx_offers_main_link ON x.main_link = px.url "
    "WHERE px.store = pl.store AND px.product_id = pl.product_id "
    "AND x.price_cents = o.price_cents AND x.kind = 'product' AND x.deleted = 0 "
    f"AND {_not_repost('x', 'xr')} "
    "AND (x.posted_at, x.channel_id, x.message_id) > (o.posted_at, o.channel_id, o.message_id) "
    f"AND julianday(x.posted_at) - julianday(o.posted_at) <= {_COLLAPSE_DAYS}))"
)

# Channels of the offers `o` hides (same product and price, older, within 24 h, visible).
_SEEN_CHANNELS = (
    "(SELECT GROUP_CONCAT(DISTINCT h.channel_id) FROM product_links ph "
    "CROSS JOIN offers h INDEXED BY idx_offers_main_link ON h.main_link = ph.url "
    "WHERE pl.product_id IS NOT NULL AND o.price_cents IS NOT NULL "
    "AND ph.store = pl.store AND ph.product_id = pl.product_id "
    "AND h.price_cents = o.price_cents AND h.kind = 'product' AND h.deleted = 0 "
    f"AND {_not_repost('h', 'hr')} "
    "AND (h.posted_at, h.channel_id, h.message_id) < (o.posted_at, o.channel_id, o.message_id) "
    f"AND julianday(o.posted_at) - julianday(h.posted_at) <= {_COLLAPSE_DAYS}) AS seen_channels"
)
_IMAGE = (
    "CASE WHEN pl.kind = 'product' AND pl.product_id IS NOT NULL THEN pl.image_url END AS image_url"
)

_CARD_COLUMNS = (
    "o.channel_id, o.message_id, o.posted_at, o.title, o.price_cents, o.store, o.main_link, "
    "o.has_photo, o.sold_out, o.deleted, o.comparable, o.kind, o.coupons, o.coupon_discount, "
    "o.coupon_min_cents, o.coupon_scope, o.redeem_link, o.cart_link, o.coupon_tiers, o.text, "
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


def _seen_channels(row: sqlite3.Row, keys: set[str]) -> tuple[int, ...]:
    own = int(row["channel_id"])
    if "seen_channels" not in keys or row["seen_channels"] is None:
        return (own,)
    others = sorted({int(c) for c in str(row["seen_channels"]).split(",")} - {own})
    return (own, *others)


def _card(row: sqlite3.Row) -> OfferCard:
    keys = set(row.keys())
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
        comparable=bool(row["comparable"]),
        repost_count=int(row["repost_count"]),
        kind=OfferKind(row["kind"]),
        coupons=tuple(json.loads(row["coupons"])) if row["coupons"] else (),
        coupon_discount=row["coupon_discount"],
        coupon_min_cents=(
            None if row["coupon_min_cents"] is None else int(row["coupon_min_cents"])
        ),
        coupon_scope=row["coupon_scope"],
        redeem_link=row["redeem_link"],
        cart_link=row["cart_link"],
        text=row["text"],
        coupon_tiers=decode_tiers(row["coupon_tiers"]),
        image_url=row["image_url"] if "image_url" in keys else None,
        seen_channel_ids=_seen_channels(row, keys),
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _cursor_of(card: OfferCard) -> FeedCursor:
    return FeedCursor(card.posted_at, card.channel_id, card.message_id)


class SqliteOfferQueries:
    # Served by idx_offers_store_kind_feed; no LIMIT, because the price filter runs in Python.
    ACTIVE_COUPONS_SQL = (
        "SELECT * FROM offers WHERE store = ? AND kind = 'coupon' AND posted_at >= ? "
        "AND deleted = 0 AND sold_out = 0 "
        "ORDER BY posted_at DESC, channel_id DESC, message_id DESC"
    )

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._repo = SqliteOfferRepository(conn)

    @staticmethod
    def _feed_where(f: FeedFilter) -> tuple[list[str], list[object]]:
        where = [_NOT_REPOST, "o.kind = 'product'"]
        unfiltered = (
            (f.q is None or fts_query(f.q) is None)
            and f.min_cents is None
            and f.max_cents is None
            and not f.stores
            and not f.priced_only
            and f.channel_id is None
        )
        if unfiltered:
            where.append(_NOT_SAME_PRODUCT)
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
        return where, params

    @staticmethod
    def _coupon_where(f: CouponFilter) -> tuple[list[str], list[object]]:
        where = ["o.kind = 'coupon'", "o.deleted = 0", _NOT_REPOST]
        params: list[object] = []
        if f.since is not None:
            where.append("o.posted_at >= ?")
            params.append(to_iso(f.since))
        if f.stores:
            where.append(f"o.store IN ({', '.join('?' * len(f.stores))})")
            params.extend(f.stores)
        if f.q:
            like = "%" + _escape_like(f.q) + "%"
            clauses = [f"o.{col} LIKE ? ESCAPE '\\'" for col in ("title", "store")]
            # `coupons` is a JSON array: match its elements, never the brackets or quotes.
            clauses.append(
                "EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid(o.coupons) THEN o.coupons "
                "ELSE '[]' END) WHERE value LIKE ? ESCAPE '\\')"
            )
            params.extend([like] * len(clauses))
            if f.q_stores:
                clauses.append(f"o.store IN ({', '.join('?' * len(f.q_stores))})")
                params.extend(f.q_stores)
            where.append(f"({' OR '.join(clauses)})")
        return where, params

    def _page(
        self,
        from_clause: str,
        columns: str,
        where: list[str],
        params: list[object],
        cursor: FeedCursor | None,
        limit: int,
    ) -> FeedPage:
        if cursor is not None:
            where = [*where, "(o.posted_at, o.channel_id, o.message_id) < (?, ?, ?)"]
            params = [*params, to_iso(cursor.posted_at), cursor.channel_id, cursor.message_id]
        rows = self._conn.execute(
            f"SELECT {columns} FROM {from_clause} WHERE {' AND '.join(where)} "
            "ORDER BY o.posted_at DESC, o.channel_id DESC, o.message_id DESC LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
        cards = tuple(_card(r) for r in rows[:limit])
        more = len(rows) > limit
        return FeedPage(cards, _cursor_of(cards[-1]) if more and cards else None)

    def _count_after(
        self, from_clause: str, where: list[str], params: list[object], since: FeedCursor
    ) -> int:
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM {from_clause} WHERE {' AND '.join(where)} "
            "AND (o.posted_at, o.channel_id, o.message_id) > (?, ?, ?)",
            (*params, to_iso(since.posted_at), since.channel_id, since.message_id),
        ).fetchone()
        return int(row[0])

    def feed(self, f: FeedFilter, cursor: FeedCursor | None, limit: int = 30) -> FeedPage:
        where, params = self._feed_where(f)
        collapse = _NOT_SAME_PRODUCT in where
        columns = f"{_CARD_COLUMNS}, {_IMAGE}" + (f", {_SEEN_CHANNELS}" if collapse else "")
        return self._page(_FEED_FROM, columns, where, params, cursor, limit)

    def coupons(self, f: CouponFilter, cursor: FeedCursor | None, limit: int = 30) -> FeedPage:
        where, params = self._coupon_where(f)
        return self._page(_OFFERS_FROM, _CARD_COLUMNS, where, params, cursor, limit)

    def count_feed_after(self, f: FeedFilter, since: FeedCursor) -> int:
        where, params = self._feed_where(f)
        return self._count_after(_FEED_FROM, where, params, since)

    def count_coupons_after(self, f: CouponFilter, since: FeedCursor) -> int:
        where, params = self._coupon_where(f)
        return self._count_after(_OFFERS_FROM, where, params, since)

    def active_coupons(
        self,
        store: str,
        since: datetime,
        price_cents: int | None,
        exclude: tuple[int, int] | None,
        limit: int = 3,
    ) -> list[ActiveCouponView]:
        rows = self._conn.execute(self.ACTIVE_COUPONS_SQL, (store, to_iso(since))).fetchall()
        views: list[ActiveCouponView] = []
        for row in rows:
            c = to_offer(row)
            if (c.channel_id, c.message_id) == exclude or not c.coupons:
                continue
            discount, min_cents, codes = c.coupon_discount or "", c.coupon_min_cents, c.coupons
            if price_cents is not None:
                tier = applicable_tier(c.coupon_tiers, min_cents, discount, codes, price_cents)
                if tier is None:
                    continue
                discount, min_cents, codes = tier.discount, tier.min_cents, tier.codes
            views.append(
                ActiveCouponView(
                    c.channel_id, c.message_id, c.posted_at, discount, min_cents, codes
                )
            )
            if len(views) >= limit:
                break
        return views

    def coupon_stores(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT o.store FROM offers o WHERE o.kind = 'coupon' AND o.deleted = 0 "
            f"AND o.store IS NOT NULL AND {_NOT_REPOST} ORDER BY o.store"
        ).fetchall()
        return [str(r[0]) for r in rows]

    def coupon_counts(self, now: datetime, hours: int = 24) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT o.store, COUNT(*) FROM offers o WHERE o.kind = 'coupon' AND o.deleted = 0 "
            f"AND o.posted_at >= ? AND o.store IS NOT NULL AND {_NOT_REPOST} GROUP BY o.store",
            (to_iso(now - timedelta(hours=hours)),),
        ).fetchall()
        return {str(r[0]): int(r[1]) for r in rows}

    def product(
        self,
        wish_id: int,
        now: datetime,
        range_days: int | None,
        cursor: FeedCursor | None,
        limit: int = 30,
    ) -> ProductHistory:
        dominant = self._repo.dominant_key(wish_id)
        stats = product_stats(self._repo.priced_points(wish_id, dominant=dominant), now)
        since = None if range_days is None else to_iso(now - timedelta(days=range_days))
        matches, next_cursor = self.matches_page(wish_id, cursor, limit, dominant=dominant)
        return ProductHistory(
            stats=stats,
            points=self._points(wish_id, since, dominant=dominant),
            matches=matches,
            next_cursor=next_cursor,
            retro=self._repo.get_retro_run(wish_id),
        )

    def _points(
        self, wish_id: int, since: str | None, dominant: tuple[str, str] | None = None
    ) -> tuple[PricePoint, ...]:
        where = f"{_COMPARABLE_MATCH} AND m.wish_id = ?"
        params: list[object] = [wish_id]
        join = _MATCH_JOIN
        if dominant is not None:
            join = f"{_MATCH_JOIN} {_PL_JOIN}"
            where += f" AND NOT {OTHER_PRODUCT_SQL}"
            params.extend(dominant)
        if since is not None:
            where += " AND m.posted_at >= ?"
            params.append(since)
        # One pass per-day first; only the rare few-days case needs the raw rows as well.
        rows = self._conn.execute(
            "SELECT substr(m.posted_at, 1, 10) AS day, MIN(m.price_cents) AS low "
            f"FROM {join} WHERE {where} GROUP BY day ORDER BY day",
            params,
        ).fetchall()
        if len(rows) < _MIN_DAYS_FOR_DAILY:
            raw = self._conn.execute(
                f"SELECT m.posted_at, m.price_cents FROM {join} WHERE {where} "
                "ORDER BY m.posted_at, m.channel_id, m.message_id",
                params,
            ).fetchall()
            return tuple(
                PricePoint(datetime.fromisoformat(r["posted_at"]), int(r["price_cents"]))
                for r in raw
            )
        days = [(datetime.fromisoformat(r["day"]).replace(tzinfo=UTC), int(r["low"])) for r in rows]
        if len(days) > _MAX_POINTS:
            n = len(days)
            buckets = [
                days[i * n // _MAX_POINTS : (i + 1) * n // _MAX_POINTS] for i in range(_MAX_POINTS)
            ]
            days = [(b[-1][0], min(p for _, p in b)) for b in buckets]
        return tuple(PricePoint(d, p) for d, p in days)

    def matches_page(
        self,
        wish_id: int,
        cursor: FeedCursor | None,
        limit: int = 30,
        dominant: tuple[str, str] | None = None,
    ) -> tuple[tuple[MatchCard, ...], FeedCursor | None]:
        other = "0" if dominant is None else f"CASE WHEN {OTHER_PRODUCT_SQL} THEN 1 ELSE 0 END"
        where = "m.wish_id = ?"
        params: list[object] = [wish_id]
        if cursor is not None:
            where += " AND (m.posted_at, m.channel_id, m.message_id) < (?, ?, ?)"
            params.extend((to_iso(cursor.posted_at), cursor.channel_id, cursor.message_id))
        rows = self._conn.execute(
            f"SELECT {_CARD_COLUMNS}, {_IMAGE}, m.source AS source, "
            f"m.price_cents AS matched_price, {other} AS other_product "
            f"FROM {_MATCH_JOIN} {_PL_JOIN} "
            f"WHERE {where} ORDER BY m.posted_at DESC, m.channel_id DESC, m.message_id DESC "
            "LIMIT ?",
            (*(dominant or ()), *params, limit + 1),
        ).fetchall()
        page = rows[:limit]
        cards = tuple(
            MatchCard(
                _card(r),
                MatchSource(r["source"]),
                None if r["matched_price"] is None else int(r["matched_price"]),
                bool(r["other_product"]),
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
            dominant = self._repo.dominant_key(wid)
            other = "" if dominant is None else f"AND NOT {OTHER_PRODUCT_SQL} "
            rows = self._conn.execute(
                f"SELECT m.price_cents FROM {_MATCH_JOIN} {_PL_JOIN} WHERE m.wish_id = ? "
                f"AND {_COMPARABLE_MATCH} {other}"
                "ORDER BY m.posted_at DESC, m.channel_id DESC, m.message_id DESC LIMIT ?",
                (wid, *(dominant or ()), _RECENT),
            ).fetchall()
            recent = tuple(int(r[0]) for r in reversed(rows))
            out[wid] = WishSummary(recent[-1] if recent else None, int(count), recent)
        return out

    def stores_seen(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT store FROM offers WHERE store IS NOT NULL ORDER BY store"
        ).fetchall()
        return [str(r[0]) for r in rows]
