"""Link enrichment in the queries: card images, same-product collapse, other-product exclusion."""

import sqlite3
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from tests.offers.adapters._queries_helpers import T0, add_link, match, offer, put
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.offers.adapters.sqlite.queries import SqliteOfferQueries
from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository
from velkgram.offers.ports.queries import NEWS_COUNT_CAP, FeedCursor, FeedFilter
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

NOTHING = FeedFilter(None, None, None, (), False, None)
NOW = T0 + timedelta(days=30)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, MIGRATION_PACKAGES)
    yield c
    c.close()


def _feed_ids(q: SqliteOfferQueries, f: FeedFilter = NOTHING) -> list[tuple[int, int]]:
    return [(c.channel_id, c.message_id) for c in q.feed(f, None, 100).cards]


# --- images ---------------------------------------------------------------------------------


def test_card_image_only_for_product_link_with_product_id(conn: sqlite3.Connection) -> None:
    add_link(conn, "https://l/a", product_id="A", image_url="https://img/a.jpg")
    add_link(
        conn, "https://l/b", product_id=None, image_url="https://img/b.jpg", kind="not_product"
    )
    add_link(conn, "https://l/c", store="kabum", product_id="C", image_url=None)
    add_link(conn, "https://l/d", product_id=None, image_url="https://img/d.jpg")  # no item id
    put(
        conn,
        offer(1, link="https://l/a"),
        offer(2, link="https://l/b"),
        offer(3, link="https://l/c"),
        offer(4, link="https://l/d"),
        offer(5, link="https://l/unknown"),
        offer(6, link=None),
    )
    cards = {c.message_id: c for c in SqliteOfferQueries(conn).feed(NOTHING, None, 50).cards}
    assert cards[1].image_url == "https://img/a.jpg"
    assert all(cards[m].image_url is None for m in (2, 3, 4, 5, 6))


def test_amazon_product_without_a_scraped_image_gets_the_asin_image(
    conn: sqlite3.Connection,
) -> None:
    asin_image = "https://m.media-amazon.com/images/P/B0000WS6QI.01._SCLZZZZZZZ_.jpg"
    add_link(conn, "https://l/a", product_id="B0000WS6QI", image_url=None)
    add_link(conn, "https://l/b", product_id="B0000AW09Q", image_url="https://img/real.jpg")
    add_link(conn, "https://l/c", store="shopee", product_id="1.2", image_url=None)
    add_link(conn, "https://l/d", product_id=None, image_url=None)
    add_link(conn, "https://l/e", product_id="B0E", image_url=None, kind="not_product")
    put(
        conn,
        offer(1, link="https://l/a"),
        offer(2, link="https://l/b"),
        offer(3, link="https://l/c"),
        offer(4, link="https://l/d"),
        offer(5, link="https://l/e"),
    )
    cards = {c.message_id: c for c in SqliteOfferQueries(conn).feed(NOTHING, None, 50).cards}
    assert cards[1].image_url == asin_image
    assert cards[2].image_url == "https://img/real.jpg"  # a scraped image always wins
    assert all(cards[m].image_url is None for m in (3, 4, 5))


def test_match_card_carries_image(conn: sqlite3.Connection) -> None:
    add_link(conn, "https://l/a", product_id="A", image_url="https://img/a.jpg")
    o = offer(1, link="https://l/a")
    put(conn, o)
    SqliteOfferRepository(conn).add_match(match(1, o))
    cards, _ = SqliteOfferQueries(conn).matches_page(1, None)
    assert cards[0].card.image_url == "https://img/a.jpg"


# --- collapse -------------------------------------------------------------------------------


def _same(conn: sqlite3.Connection) -> None:
    add_link(conn, "https://l/a1", product_id="A")
    add_link(conn, "https://l/a2", product_id="A")  # another link, same product


def test_same_product_and_price_collapses_to_one_card_with_channels(
    conn: sqlite3.Connection,
) -> None:
    _same(conn)
    put(
        conn,
        offer(1, channel_id=1, link="https://l/a1", at=T0),
        offer(2, channel_id=2, link="https://l/a2", at=T0 + timedelta(hours=2)),
    )
    cards = SqliteOfferQueries(conn).feed(NOTHING, None).cards
    assert [(c.channel_id, c.message_id) for c in cards] == [(2, 2)]
    assert cards[0].seen_channel_ids == (2, 1)


def test_different_price_does_not_collapse(conn: sqlite3.Connection) -> None:
    _same(conn)
    put(
        conn,
        offer(1, link="https://l/a1", price=1000),
        offer(2, link="https://l/a2", price=1100),
    )
    assert len(_feed_ids(SqliteOfferQueries(conn))) == 2


@pytest.mark.parametrize(
    ("gap", "collapsed"),
    [
        (timedelta(hours=23, minutes=59), True),
        (timedelta(hours=24, minutes=1), False),
    ],
)
def test_collapse_window_is_24h_also_across_midnight(
    conn: sqlite3.Connection, gap: timedelta, collapsed: bool
) -> None:
    _same(conn)
    start = T0.replace(hour=23, minute=30)
    put(
        conn,
        offer(1, link="https://l/a1", at=start),
        offer(2, channel_id=2, link="https://l/a2", at=start + gap),
    )
    cards = SqliteOfferQueries(conn).feed(NOTHING, None).cards
    assert len(cards) == (1 if collapsed else 2)
    assert cards[0].seen_channel_ids == ((2, 1) if collapsed else (2,))


def test_null_product_id_never_collapses(conn: sqlite3.Connection) -> None:
    add_link(conn, "https://l/n1", product_id=None)
    add_link(conn, "https://l/n2", product_id=None)
    put(conn, offer(1, link="https://l/n1"), offer(2, link="https://l/n2"))
    put(conn, offer(3, link="https://l/unenriched"), offer(4, link="https://l/unenriched"))
    assert len(_feed_ids(SqliteOfferQueries(conn))) == 4


def test_different_store_same_product_id_does_not_collapse(conn: sqlite3.Connection) -> None:
    add_link(conn, "https://l/a1", store="amazon", product_id="A")
    add_link(conn, "https://l/a2", store="kabum", product_id="A")
    put(conn, offer(1, link="https://l/a1"), offer(2, link="https://l/a2"))
    assert len(_feed_ids(SqliteOfferQueries(conn))) == 2


@pytest.mark.parametrize(
    "flt",
    [
        FeedFilter("ssd", None, None, (), False, None),
        FeedFilter(None, 1, None, (), False, None),
        FeedFilter(None, None, 10**9, (), False, None),
        FeedFilter(None, None, None, ("amazon",), False, None),
        FeedFilter(None, None, None, (), True, None),
        FeedFilter(None, None, None, (), False, 1),
    ],
)
def test_any_filter_turns_collapse_off(conn: sqlite3.Connection, flt: FeedFilter) -> None:
    _same(conn)
    put(
        conn,
        offer(1, channel_id=1, link="https://l/a1", at=T0),
        offer(2, channel_id=1, link="https://l/a2", at=T0 + timedelta(hours=1)),
    )
    cards = SqliteOfferQueries(conn).feed(flt, None).cards
    assert len(cards) == 2
    assert all(c.seen_channel_ids == (c.channel_id,) for c in cards)


def test_original_and_forward_with_same_link_give_one_card(conn: sqlite3.Connection) -> None:
    add_link(conn, "https://l/a1", product_id="A")
    put(
        conn,
        offer(1, channel_id=1, link="https://l/a1", at=T0),
        offer(2, channel_id=2, link="https://l/a1", at=T0 + timedelta(minutes=1), origin=(1, 1)),
    )
    cards = SqliteOfferQueries(conn).feed(NOTHING, None).cards
    assert [(c.channel_id, c.message_id) for c in cards] == [(1, 1)]
    assert cards[0].seen_channel_ids == (1,)  # a forward is a repost, not another channel


def test_three_offers_at_one_instant_collapse_without_losing_the_chips(
    conn: sqlite3.Connection,
) -> None:
    add_link(conn, "https://l/a1", product_id="A")
    put(conn, *(offer(m, channel_id=m, link="https://l/a1", at=T0) for m in (1, 2, 3)))
    cards = SqliteOfferQueries(conn).feed(NOTHING, None).cards
    assert [(c.channel_id, c.message_id) for c in cards] == [(3, 3)]
    assert set(cards[0].seen_channel_ids) == {1, 2, 3}
    assert cards[0].seen_channel_ids[0] == 3


def test_paging_with_limit_one_across_a_collapsed_group_has_no_repeats_or_gaps(
    conn: sqlite3.Connection,
) -> None:
    _same(conn)
    put(
        conn,
        offer(1, channel_id=1, link="https://l/a1", at=T0),
        offer(2, channel_id=2, link="https://l/a2", at=T0 + timedelta(hours=1)),
        offer(3, channel_id=3, link="https://l/a1", at=T0 + timedelta(hours=2)),
        offer(4, channel_id=1, link="https://l/other", at=T0 + timedelta(hours=1, minutes=30)),
        offer(5, channel_id=1, link="https://l/other2", at=T0 - timedelta(hours=1)),
    )
    q = SqliteOfferQueries(conn)
    seen: list[tuple[int, int]] = []
    cursor: FeedCursor | None = None
    for _ in range(10):
        page = q.feed(NOTHING, cursor, 1)
        seen += [(c.channel_id, c.message_id) for c in page.cards]
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == [(3, 3), (1, 4), (1, 5)]
    assert seen == _feed_ids(q)


def test_count_feed_after_agrees_with_the_collapsed_list(conn: sqlite3.Connection) -> None:
    _same(conn)
    put(
        conn,
        offer(1, channel_id=1, link="https://l/a1", at=T0),
        offer(2, channel_id=2, link="https://l/a2", at=T0 + timedelta(hours=1)),
        offer(3, channel_id=3, link="https://l/a1", at=T0 + timedelta(hours=2)),
        offer(4, channel_id=1, link="https://l/o", at=T0 + timedelta(hours=3)),
    )
    q = SqliteOfferQueries(conn)
    since = FeedCursor(T0 - timedelta(minutes=1), 0, 0)
    assert q.count_feed_after(NOTHING, since) == len(_feed_ids(q)) == 2
    mid = FeedCursor(T0 + timedelta(hours=1), 2, 2)
    assert q.count_feed_after(NOTHING, mid) == 2


def test_coupons_and_matches_page_still_work_with_links(conn: sqlite3.Connection) -> None:
    from velkgram.offers.domain.models import OfferKind
    from velkgram.offers.ports.queries import CouponFilter

    add_link(conn, "https://l/a1", product_id="A")
    c = offer(1, kind=OfferKind.coupon, coupon=("X",))
    p = offer(2, link="https://l/a1")
    put(conn, c, p)
    SqliteOfferRepository(conn).add_match(match(1, p))
    q = SqliteOfferQueries(conn)
    assert [x.message_id for x in q.coupons(CouponFilter(), None).cards] == [1]
    assert q.coupons(CouponFilter(), None).cards[0].image_url is None
    assert q.count_coupons_after(CouponFilter(), FeedCursor(T0 - timedelta(days=1), 0, 0)) == 1
    assert len(q.matches_page(1, None)[0]) == 1


# --- plan shape -----------------------------------------------------------------------------


def test_collapse_exists_uses_indexes_and_feed_has_no_full_scan(conn: sqlite3.Connection) -> None:
    traced: list[str] = []
    conn.set_trace_callback(traced.append)
    SqliteOfferQueries(conn).feed(NOTHING, FeedCursor(NOW, 1, 1), 30)
    conn.set_trace_callback(None)
    sql = next(s for s in traced if "FROM offers o" in s and "ORDER BY" in s)
    plan = [r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, _params_of(sql))]
    assert not any(line.startswith("SCAN o") for line in plan), plan
    assert any("SEARCH px" in line and "INDEX" in line for line in plan), plan
    assert any("SEARCH x" in line and "INDEX" in line for line in plan), plan


def _params_of(sql: str) -> list[object]:
    return []  # the trace callback expands the bound parameters into the statement text


# --- other product --------------------------------------------------------------------------


def _wish_with_keys(conn: sqlite3.Connection, keys: list[str | None]) -> None:
    repo = SqliteOfferRepository(conn)
    for i, k in enumerate(keys, start=1):
        url = f"https://l/{i}"
        if k is not None:
            add_link(conn, url, product_id=k)
        o = offer(i, at=T0 + timedelta(days=i), price=1000 * i, link=url)
        put(conn, o)
        repo.add_match(match(1, o))


def test_other_product_is_excluded_from_stats_points_and_summary(
    conn: sqlite3.Connection,
) -> None:
    _wish_with_keys(conn, ["A", "A", "A", "B"])  # prices 1000, 2000, 3000, 4000(B)
    q = SqliteOfferQueries(conn)
    h = q.product(1, NOW, None, None)
    assert [p.price_cents for p in h.points] == [1000, 2000, 3000]
    assert (h.stats.last_cents, h.stats.match_count) == (3000, 4)
    s = q.summaries([1])[1]
    assert s.last_cents == 3000
    assert s.recent_prices == (1000, 2000, 3000)
    assert s.match_count == 4


def test_other_product_kept_in_matches_page_flagged(conn: sqlite3.Connection) -> None:
    _wish_with_keys(conn, ["A", "A", "A", "B"])
    h = SqliteOfferQueries(conn).product(1, NOW, None, None)
    assert [m.card.message_id for m in h.matches] == [4, 3, 2, 1]
    assert [m.other_product for m in h.matches] == [True, False, False, False]
    assert h.matches[0].matched_price_cents == 4000


def test_no_dominant_excludes_nothing(conn: sqlite3.Connection) -> None:
    _wish_with_keys(conn, ["A", "B"])
    h = SqliteOfferQueries(conn).product(1, NOW, None, None)
    assert len(h.points) == 2
    assert not any(m.other_product for m in h.matches)


def test_unkeyed_matches_are_never_other_product(conn: sqlite3.Connection) -> None:
    _wish_with_keys(conn, ["A", "A", "A", None])
    h = SqliteOfferQueries(conn).product(1, NOW, None, None)
    assert len(h.points) == 4
    assert not any(m.other_product for m in h.matches)


def _dominant_statements(conn: sqlite3.Connection, run: Callable[[], object]) -> int:
    seen: list[str] = []
    conn.set_trace_callback(seen.append)
    try:
        run()
    finally:
        conn.set_trace_callback(None)
    return sum("GROUP BY m.wish_id, pl.store, pl.product_id" in sql for sql in seen)


def test_dominant_key_is_computed_once_per_product_call(conn: sqlite3.Connection) -> None:
    _wish_with_keys(conn, ["A", "A", "A", "B"])
    q = SqliteOfferQueries(conn)
    assert _dominant_statements(conn, lambda: q.product(1, NOW, None, None)) == 1


def test_summaries_compute_every_dominant_key_in_one_query(conn: sqlite3.Connection) -> None:
    _wish_with_keys(conn, ["A", "A", "A", "B"])
    q = SqliteOfferQueries(conn)
    assert _dominant_statements(conn, lambda: q.summaries([1, 2, 3, 4])) == 1
    assert SqliteOfferRepository(conn).dominant_keys([1, 2]) == {1: ("amazon", "A"), 2: None}


def test_dominant_key_value(conn: sqlite3.Connection) -> None:
    _wish_with_keys(conn, ["A", "A", "A", "B"])
    assert SqliteOfferRepository(conn).dominant_key(1) == ("amazon", "A")
    assert SqliteOfferRepository(conn).dominant_key(2) is None


def test_count_feed_after_is_capped(conn: sqlite3.Connection) -> None:
    put(
        conn,
        *(offer(i, link=f"https://l/{i}", at=T0 + timedelta(minutes=i)) for i in range(1, 131)),
    )
    q = SqliteOfferQueries(conn)
    since = FeedCursor(T0 - timedelta(days=1), 0, 0)
    assert q.count_feed_after(NOTHING, since) == NEWS_COUNT_CAP
    near = FeedCursor(T0 + timedelta(minutes=125), 1, 125)
    assert q.count_feed_after(NOTHING, near) == 5


def test_idx_offers_main_link_exists_and_the_collapse_query_runs(conn: sqlite3.Connection) -> None:
    # The collapse EXISTS is pinned with INDEXED BY: a dropped or renamed index would make
    # it raise "no such index", so the migration must create exactly this name.
    assert "idx_offers_main_link" in {r[1] for r in conn.execute("PRAGMA index_list(offers)")}
    _same(conn)
    put(conn, offer(1, link="https://l/a1", at=T0), offer(2, link="https://l/a1", at=T0))
    assert SqliteOfferQueries(conn).feed(NOTHING, None).cards


# --- real product urls ----------------------------------------------------------------------


def _seed_product_links(conn: sqlite3.Connection) -> None:
    add_link(conn, "https://l/a", store="amazon", product_id="B0C8814GKB")
    add_link(conn, "https://l/b", store="amazon", product_id=None, kind="not_product")
    put(conn, offer(1, link="https://l/a"), offer(2, link="https://l/b"), offer(3, link=None))


def test_repository_product_urls_only_for_real_products(conn: sqlite3.Connection) -> None:
    _seed_product_links(conn)
    repo = SqliteOfferRepository(conn)
    got = repo.product_urls(["https://l/a", "https://l/b", "https://l/unknown"])
    assert got == {"https://l/a": "https://www.amazon.com.br/dp/B0C8814GKB"}
    assert repo.product_urls([]) == {}


def test_queries_product_links_keyed_by_offer_pair(conn: sqlite3.Connection) -> None:
    _seed_product_links(conn)
    q = SqliteOfferQueries(conn)
    got = q.product_links([(1, 1), (1, 2), (1, 3), (1, 99)])
    assert got == {(1, 1): "https://www.amazon.com.br/dp/B0C8814GKB"}
    assert q.product_links([]) == {}


def test_feed_card_product_url(conn: sqlite3.Connection) -> None:
    _seed_product_links(conn)
    cards = {c.message_id: c for c in SqliteOfferQueries(conn).feed(NOTHING, None, 50).cards}
    assert cards[1].product_url == "https://www.amazon.com.br/dp/B0C8814GKB"
    assert cards[2].product_url is None
    assert cards[3].product_url is None


def test_match_card_product_url(conn: sqlite3.Connection) -> None:
    add_link(
        conn, "https://l/a", store="magalu", product_id="abc", final_url="https://m.test/p/abc"
    )
    o = offer(1, link="https://l/a")
    put(conn, o)
    SqliteOfferRepository(conn).add_match(match(1, o))
    cards, _ = SqliteOfferQueries(conn).matches_page(1, None)
    assert cards[0].card.product_url == "https://m.test/p/abc"
