import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from tests.offers.adapters._queries_helpers import T0, offer, put
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.offers.adapters.sqlite.queries import SqliteOfferQueries, fts_query
from velkgram.offers.domain.models import CouponTier, OfferKind
from velkgram.offers.ports.queries import CouponFilter, FeedFilter
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

NO_FILTER = FeedFilter(None, None, None, (), False, None)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, MIGRATION_PACKAGES)
    yield c
    c.close()


def _ids(conn: sqlite3.Connection, f: FeedFilter) -> list[int]:
    return [c.message_id for c in SqliteOfferQueries(conn).feed(f, None).cards]


def test_fts_query_builds_quoted_prefix_terms() -> None:
    assert fts_query('ssd "x') == '"ssd" """x"*'
    assert fts_query("- *") is None
    assert fts_query("   ") is None


def test_feed_newest_first_and_keyset_pagination(conn: sqlite3.Connection) -> None:
    put(conn, *(offer(i) for i in range(1, 8)))
    q = SqliteOfferQueries(conn)
    p1 = q.feed(NO_FILTER, None, limit=3)
    assert [c.message_id for c in p1.cards] == [7, 6, 5]
    assert p1.next_cursor is not None
    p2 = q.feed(NO_FILTER, p1.next_cursor, limit=3)
    assert [c.message_id for c in p2.cards] == [4, 3, 2]
    p3 = q.feed(NO_FILTER, p2.next_cursor, limit=3)
    assert [c.message_id for c in p3.cards] == [1]
    assert p3.next_cursor is None


def test_feed_pagination_breaks_ties_by_channel_and_message(conn: sqlite3.Connection) -> None:
    put(conn, *(offer(i, channel_id=c, at=T0) for c in (1, 2) for i in (1, 2)))
    q = SqliteOfferQueries(conn)
    p1 = q.feed(NO_FILTER, None, limit=3)
    p2 = q.feed(NO_FILTER, p1.next_cursor, limit=3)
    seen = [(c.channel_id, c.message_id) for c in (*p1.cards, *p2.cards)]
    assert seen == [(2, 2), (2, 1), (1, 2), (1, 1)]


def test_feed_filter_q(conn: sqlite3.Connection) -> None:
    put(
        conn,
        offer(1, title="SSD Kingston", text="SSD Kingston 1TB"),
        offer(2, title="Mouse", text="Mouse gamer"),
    )
    assert _ids(conn, FeedFilter("kings", None, None, (), False, None)) == [1]


def test_feed_filter_min(conn: sqlite3.Connection) -> None:
    put(conn, offer(1, price=100), offer(2, price=500), offer(3, price=None))
    assert _ids(conn, FeedFilter(None, 200, None, (), False, None)) == [2]


def test_feed_filter_max(conn: sqlite3.Connection) -> None:
    put(conn, offer(1, price=100), offer(2, price=500), offer(3, price=None))
    assert _ids(conn, FeedFilter(None, None, 200, (), False, None)) == [1]


def test_feed_filter_stores(conn: sqlite3.Connection) -> None:
    put(conn, offer(1, store="amazon"), offer(2, store="kabum"), offer(3, store="magalu"))
    assert _ids(conn, FeedFilter(None, None, None, ("amazon", "magalu"), False, None)) == [3, 1]


def test_feed_filter_priced_only(conn: sqlite3.Connection) -> None:
    put(conn, offer(1, price=None), offer(2, price=10))
    assert _ids(conn, FeedFilter(None, None, None, (), True, None)) == [2]


def test_feed_filter_channel(conn: sqlite3.Connection) -> None:
    put(conn, offer(1, channel_id=1), offer(2, channel_id=2))
    assert _ids(conn, FeedFilter(None, None, None, (), False, 2)) == [2]


def test_feed_search_ignores_accents(conn: sqlite3.Connection) -> None:
    put(conn, offer(1, title="Cafeteira Elétrica", text="Cafeteira Elétrica 110v"))
    assert _ids(conn, FeedFilter("eletrica", None, None, (), False, None)) == [1]
    assert _ids(conn, FeedFilter("ELÉTRICA", None, None, (), False, None)) == [1]


@pytest.mark.parametrize("q", ['"', "-", "*", "AND", "(", "'", "NOT ssd"])
def test_feed_search_tolerates_fts_syntax(conn: sqlite3.Connection, q: str) -> None:
    put(conn, offer(1))
    SqliteOfferQueries(conn).feed(FeedFilter(q, None, None, (), False, None), None)


def test_feed_hides_forward_and_counts_reposts(conn: sqlite3.Connection) -> None:
    put(
        conn,
        offer(1, channel_id=1),
        offer(2, channel_id=2, origin=(1, 1)),
        offer(3, channel_id=3, origin=(1, 1)),
        offer(4, channel_id=4, origin=(9, 9)),  # origin unknown: stays visible
    )
    cards = SqliteOfferQueries(conn).feed(NO_FILTER, None).cards
    assert {(c.channel_id, c.repost_count) for c in cards} == {(1, 2), (4, 0)}


def test_feed_includes_sold_out_and_deleted_with_flags(conn: sqlite3.Connection) -> None:
    put(conn, offer(1, sold_out=True), offer(2, deleted=True))
    by_id = {c.message_id: c for c in SqliteOfferQueries(conn).feed(NO_FILTER, None).cards}
    assert by_id[1].sold_out and not by_id[1].deleted
    assert by_id[2].deleted and not by_id[2].sold_out


def test_feed_search_skips_purged_text_but_lists_offer(conn: sqlite3.Connection) -> None:
    from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository

    put(conn, offer(1, title="Placa", text="Placa de video"))
    SqliteOfferRepository(conn).purge_text_before(T0 + timedelta(days=1))
    assert _ids(conn, NO_FILTER) == [1]
    assert _ids(conn, FeedFilter("video", None, None, (), False, None)) == []


def test_feed_never_lists_coupons(conn: sqlite3.Connection) -> None:
    put(
        conn,
        offer(1),
        offer(2, kind=OfferKind.coupon, price=None, title="Cupom Shopee", comparable=False),
    )
    assert _ids(conn, NO_FILTER) == [1]


def test_card_carries_coupon_data_and_post_text(conn: sqlite3.Connection) -> None:
    put(
        conn,
        offer(1, coupon=("KORUJAO", "ZAFA10"), text="SSD\ncupom: KORUJAO"),
        offer(2, kind=OfferKind.coupon, price=None, coupon=("QIP98Q1ZXO",)),
    )
    queries = SqliteOfferQueries(conn)
    product = queries.feed(NO_FILTER, None).cards[0]
    coupon = queries.coupons(CouponFilter(), None).cards[0]
    assert product.kind is OfferKind.product
    assert product.coupons == ("KORUJAO", "ZAFA10")
    assert product.text == "SSD\ncupom: KORUJAO"
    assert coupon.kind is OfferKind.coupon
    assert (coupon.coupon_discount, coupon.coupon_min_cents) == ("R$ 10 OFF", 4000)
    assert coupon.redeem_link == "https://x.test/resgate"
    assert coupon.coupon_tiers == (CouponTier("R$ 10 OFF", 4000),)
