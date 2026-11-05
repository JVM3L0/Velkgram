import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from tests.offers.adapters._queries_helpers import T0, offer, put
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.offers.adapters.sqlite.queries import SqliteOfferQueries
from velkgram.offers.domain.models import Offer, OfferKind
from velkgram.offers.ports.queries import CouponFilter, FeedCursor
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

NOW = T0 + timedelta(days=3)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, MIGRATION_PACKAGES)
    yield c
    c.close()


def coupon(mid: int, age_h: float = 1, **kw: object) -> Offer:
    base: dict[str, object] = {
        "kind": OfferKind.coupon,
        "price": None,
        "title": "Cupom X",
        "comparable": False,
        "store": "shopee",
        "at": NOW - timedelta(hours=age_h),
    }
    return offer(mid, **{**base, **kw})  # type: ignore[arg-type]


def _ids(conn: sqlite3.Connection, f: CouponFilter, limit: int = 30) -> list[int]:
    return [c.message_id for c in SqliteOfferQueries(conn).coupons(f, None, limit).cards]


def test_coupons_are_newest_first_coupon_kind_only_and_skip_deleted(
    conn: sqlite3.Connection,
) -> None:
    put(conn, coupon(1, 5), coupon(2, 1), coupon(3, 2, deleted=True), offer(4, at=NOW))
    assert _ids(conn, CouponFilter()) == [2, 1]


def test_coupons_keyset_pagination_walks_every_row_once(conn: sqlite3.Connection) -> None:
    put(conn, *(coupon(i, i) for i in range(1, 8)))
    q = SqliteOfferQueries(conn)
    seen: list[int] = []
    cursor: FeedCursor | None = None
    while True:
        page = q.coupons(CouponFilter(), cursor, 3)
        seen += [c.message_id for c in page.cards]
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == [1, 2, 3, 4, 5, 6, 7]


def test_coupons_since_keeps_only_recent_ones(conn: sqlite3.Connection) -> None:
    put(conn, coupon(1, 30), coupon(2, 23), coupon(3, 1))
    since = NOW - timedelta(hours=24)
    assert _ids(conn, CouponFilter(since=since)) == [3, 2]
    assert _ids(conn, CouponFilter()) == [3, 2, 1]


def test_coupons_store_filter(conn: sqlite3.Connection) -> None:
    put(conn, coupon(1, store="shopee"), coupon(2, store="amazon"), coupon(3, store=None))
    assert _ids(conn, CouponFilter(store="amazon")) == [2]


def test_coupons_search_matches_code_title_or_store(conn: sqlite3.Connection) -> None:
    put(
        conn,
        coupon(1, 1, coupon=("ZAFA10",), title="Cupom Shopee"),
        coupon(2, 2, coupon=("KORUJAO",), title="Cupom KaBuM", store="kabum"),
        coupon(3, 3, coupon=("OUTRO",), title="Cupom Amazon", store="amazon"),
    )
    assert _ids(conn, CouponFilter(q="zafa")) == [1]
    assert _ids(conn, CouponFilter(q="kabum")) == [2]
    assert _ids(conn, CouponFilter(q="AMAZ")) == [3]
    assert _ids(conn, CouponFilter(q="inexistente")) == []


def test_coupons_search_matches_extra_store_keys_and_treats_wildcards_literally(
    conn: sqlite3.Connection,
) -> None:
    put(conn, coupon(1, 1, store="mercadolivre", title="Cupom"), coupon(2, 2, title="Cupom 10%"))
    assert _ids(conn, CouponFilter(q="mercado livre", q_stores=("mercadolivre",))) == [1]
    assert _ids(conn, CouponFilter(q="%")) == [2]
    assert _ids(conn, CouponFilter(q="_")) == []


def test_coupons_hide_reposts_of_a_stored_original(conn: sqlite3.Connection) -> None:
    put(conn, coupon(1, 5), coupon(2, 1, channel_id=2, origin=(1, 1)))
    assert _ids(conn, CouponFilter()) == [1]


def test_coupon_stores_lists_only_stores_with_coupons(conn: sqlite3.Connection) -> None:
    put(
        conn,
        coupon(1, store="shopee"),
        coupon(2, store="amazon"),
        coupon(3, store=None),
        offer(4, store="magalu"),
    )
    assert SqliteOfferQueries(conn).coupon_stores() == ["amazon", "shopee"]


def test_coupon_counts_group_recent_live_coupons_by_store(conn: sqlite3.Connection) -> None:
    put(
        conn,
        coupon(1, 1, store="shopee"),
        coupon(2, 2, store="shopee"),
        coupon(3, 3, store="amazon"),
        coupon(4, 30, store="amazon"),
        coupon(5, 1, store="amazon", deleted=True),
        coupon(6, 1, store=None),
        coupon(7, 1, store="amazon", channel_id=2, origin=(1, 3)),
        offer(8, at=NOW, store="shopee"),
    )
    assert SqliteOfferQueries(conn).coupon_counts(NOW) == {"shopee": 2, "amazon": 1}
    assert SqliteOfferQueries(conn).coupon_counts(NOW, hours=48) == {"shopee": 2, "amazon": 2}


def test_coupon_queries_use_the_kind_posted_at_index(conn: sqlite3.Connection) -> None:
    put(conn, coupon(1))
    plan = " ".join(
        str(r[3])
        for r in conn.execute(
            "EXPLAIN QUERY PLAN SELECT o.message_id FROM offers o "
            "WHERE o.kind = 'coupon' AND o.deleted = 0 AND o.posted_at >= ? "
            "ORDER BY o.posted_at DESC, o.channel_id DESC, o.message_id DESC LIMIT 30",
            ("2026-01-01",),
        )
    )
    assert "idx_offers_kind_posted_at" in plan
