import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from tests.offers.adapters._queries_helpers import T0, offer, put
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.offers.adapters.sqlite.queries import SqliteOfferQueries
from velkgram.offers.domain.models import CouponTier, Offer, OfferKind
from velkgram.offers.ports.queries import ActiveCouponView
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

NOW = T0 + timedelta(days=3)
SINCE = NOW - timedelta(hours=24)

ML_TIERS = (
    CouponTier("R$ 10 OFF", 5000, None, ("ML10",)),
    CouponTier("R$ 30 OFF", 15000, None, ("ML30",)),
    CouponTier("R$ 90 OFF", 50000, None, ("ML90",)),
)


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
        "coupon": ("CODE",),
    }
    return offer(mid, **{**base, **kw})  # type: ignore[arg-type]


def _active(
    conn: sqlite3.Connection,
    price: int | None = None,
    exclude: tuple[int, int] | None = None,
    limit: int = 3,
) -> list[ActiveCouponView]:
    return SqliteOfferQueries(conn).active_coupons("shopee", SINCE, price, exclude, limit)


def _ids(views: list[ActiveCouponView]) -> list[int]:
    return [v.message_id for v in views]


def test_newest_first_and_window_store_kind_filters(conn: sqlite3.Connection) -> None:
    put(
        conn,
        coupon(1, 5),
        coupon(2, 1),
        coupon(3, 30),  # outside the 24 h window
        coupon(4, 1, store="amazon"),
        offer(5, at=NOW, store="shopee"),  # a product
    )
    assert _ids(_active(conn)) == [2, 1]


def test_since_boundary_is_inclusive(conn: sqlite3.Connection) -> None:
    put(
        conn,
        coupon(1, 24),  # exactly at `since`
        coupon(2, 24 + 1 / 3600),  # one second before
    )
    assert _ids(_active(conn)) == [1]


def test_codeless_sold_out_and_deleted_coupons_are_dropped(conn: sqlite3.Connection) -> None:
    put(
        conn,
        coupon(1, 1, coupon=()),
        coupon(2, 2, sold_out=True),
        coupon(3, 3, deleted=True),
        coupon(4, 4),
    )
    assert _ids(_active(conn)) == [4]


def test_exclude_drops_the_given_coupon(conn: sqlite3.Connection) -> None:
    put(conn, coupon(1, 1), coupon(2, 2))
    assert _ids(_active(conn, exclude=(1, 1))) == [2]


def test_without_a_price_the_view_uses_coupon_level_values(conn: sqlite3.Connection) -> None:
    put(conn, coupon(1, 1, coupon=("A", "B")))
    [view] = _active(conn)
    assert view == ActiveCouponView(
        channel_id=1,
        message_id=1,
        posted_at=NOW - timedelta(hours=1),
        discount="R$ 10 OFF",
        min_cents=4000,
        codes=("A", "B"),
    )


def test_price_filter_keeps_only_coupons_the_price_reaches(conn: sqlite3.Connection) -> None:
    put(conn, coupon(1, 1), coupon(2, 2, coupon_tiers=(CouponTier("R$ 5 OFF", 9000),)))
    assert _ids(_active(conn, price=5000)) == [1]
    assert _ids(_active(conn, price=9000)) == [1, 2]


def test_mercado_livre_tier_is_chosen_for_the_price(conn: sqlite3.Connection) -> None:
    put(conn, coupon(1, 1, store="shopee", coupon_tiers=ML_TIERS, coupon=("ML10",)))
    assert [(v.discount, v.min_cents, v.codes) for v in _active(conn, price=20000)] == [
        ("R$ 30 OFF", 15000, ("ML30",))
    ]
    assert [(v.discount, v.codes) for v in _active(conn, price=60000)] == [("R$ 90 OFF", ("ML90",))]
    assert _active(conn, price=4000) == []


def test_limit_applies_after_the_price_filter(conn: sqlite3.Connection) -> None:
    high = (CouponTier("R$ 50 OFF", 90000),)
    put(conn, *(coupon(i, i, coupon_tiers=high) for i in range(1, 5)), coupon(9, 10))
    assert _ids(_active(conn, price=5000, limit=1)) == [9]
    assert _ids(_active(conn, limit=3)) == [1, 2, 3]


def test_query_plan_uses_the_store_kind_feed_index(conn: sqlite3.Connection) -> None:
    sql = SqliteOfferQueries.ACTIVE_COUPONS_SQL
    plan = conn.execute(f"EXPLAIN QUERY PLAN {sql}", ("shopee", "2026-01-01")).fetchall()
    assert any("idx_offers_store_kind_feed" in str(r[3]) for r in plan)


def test_view_carries_the_applicable_tiers_cap_only_with_a_price(conn: sqlite3.Connection) -> None:
    tiers = (CouponTier("10% OFF", None, 4000, ("CAPPED",)),)
    put(conn, coupon(1, coupon_tiers=tiers))
    assert [v.cap_cents for v in _active(conn, 30000)] == [4000]
    assert [v.cap_cents for v in _active(conn, None)] == [None]
