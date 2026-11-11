"""Volume check: 50,000 offers (and their messages) must page and search fast.

Every timed read must finish under 150 ms and must not `SCAN offers` without an index; the
plan check runs EXPLAIN QUERY PLAN on the statements the query port really executed.

Measured on the dev machine (WSL2, median of 3 runs after a warm-up), migrations 004 and 005
applied: feed first page 0.2 ms, 100th page 0.3 ms; filtered feed 0.3 / 0.3 ms; coupons first
page 0.3 ms, 100th page 0.3 ms, store+since 0.3 ms; FTS search "raro" 3.3 ms, "marca42" 0.5 ms,
"produto" 5.5 ms; one channel 0.2 ms (50th page 0.2 ms), channel+store 0.2 ms, narrow price band
2.3 ms; product matches page (one wish, ~21k matches) first 0.3 ms, 100th 0.3 ms. The first call on
a fresh connection takes 0.3-0.4 ms (narrow price 3.1 ms).

With link enrichment (migration 006; 5,000 links, half enriched): feed first/100th page 0.7 ms,
product() on a wish with ~21k matches ~140 ms (the dominant GROUP BY, priced_points and the points
query each walk those matches), summaries() for 20 wishes ~110 ms, keyed matches page 0.4 ms.
The collapse EXISTS needs `INDEXED BY idx_offers_main_link`, otherwise SQLite scans offers by time.
"""

import json
import os
import re
import sqlite3
import statistics
import time
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from tests.offers.adapters._queries_helpers import T0
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.offers.adapters.sqlite.queries import SqliteOfferQueries
from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository, to_iso
from velkgram.offers.ports.queries import (
    NEWS_COUNT_CAP,
    CouponFilter,
    FeedCursor,
    FeedFilter,
    FeedPage,
)
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

ROWS = 50_000
LINKS = 5_000  # distinct main links; the even ones are enriched in product_links
# Shared CI runners are 2-3x slower and noisy; the plan checks (no SCAN) still guard the structure.
BOUND_S = 0.150 * (2 if os.environ.get("CI") else 1)
DEEP_PAGE = 100
STORES = ("amazon", "kabum", "magalu", "shopee", None)
NOTHING = FeedFilter(None, None, None, (), False, None)

_FULL_SCAN = re.compile(r"^SCAN (offers|o|r|x|pl|px|xo)\b(?!.*\bINDEX\b)")


@pytest.fixture(scope="module")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("volume") / "t.db"


@pytest.fixture(scope="module")
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(db_path)
    apply_migrations(c, MIGRATION_PACKAGES)
    offers = []
    messages = []
    matches = []
    for i in range(ROWS):
        at = to_iso(T0 + timedelta(seconds=30 * (i // 3)))  # three offers share each instant
        coupon = i % 7 == 0
        store = STORES[i % 5]
        channel = i % 20
        title = f"Cupom {store}" if coupon else f"Produto {i} marca{i % 97}"
        text = f"{title} oferta {'raro' if i % 5000 == 0 else 'comum'} R$ {i % 900},00"
        repost = i % 11 == 0 and i > 0
        offers.append(
            (
                channel,
                i,
                at,
                title,
                None if coupon else (i * 37) % 100000 or None,
                store,
                f"https://x.test/p{i % LINKS}",
                i % 2,
                text,
                text.lower(),
                (channel + 1) % 20 if repost else None,
                i - 1 if repost else None,
                0,
                1 if i % 13 == 0 else 0,
                at,
                "coupon" if coupon else "product",
                json.dumps([f"CODE{i}"]) if coupon else None,
                "R$ 10 OFF" if coupon else None,
                0 if coupon else 1,
            )
        )
        messages.append((channel, i, at, at, text, "[]", i % 2, "live"))
        if i % 2 == 0 and not coupon:  # one wish with ~21k matches
            matches.append((1, channel, i, offers[-1][4], at, "live", at))
        if i % 3 == 0 and not coupon:  # wishes 2..20, a few thousand matches each
            matches.append((i % 19 + 2, channel, i, offers[-1][4], at, "live", at))
    stamp = to_iso(T0)
    links = [
        (
            f"https://x.test/p{n}",
            STORES[n % 5],
            f"P{n % 1250}",
            f"https://img.test/{n}.jpg",
            stamp,
            stamp,
        )
        for n in range(0, LINKS, 2)
    ]
    with c:
        c.executemany(
            "INSERT INTO product_links (url, store, product_id, image_url, kind, status, "
            "created_at, offer_posted_at, host) VALUES (?,?,?,?,'product','done',?,?,'x.test')",
            links,
        )
        c.executemany(
            "INSERT INTO offers (channel_id, message_id, posted_at, title, price_cents, store, "
            "main_link, has_photo, text, norm_text, origin_channel_id, origin_message_id, "
            "sold_out, deleted, updated_at, kind, coupons, coupon_discount, comparable) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            offers,
        )
        c.executemany(
            "INSERT INTO messages (channel_id, message_id, date, received_at, text, links, "
            "has_photo, source) VALUES (?,?,?,?,?,?,?,?)",
            messages,
        )
        c.executemany(
            "INSERT OR IGNORE INTO offer_matches (wish_id, channel_id, message_id, price_cents, "
            "posted_at, source, matched_at) VALUES (?,?,?,?,?,?,?)",
            matches,
        )
    yield c
    c.close()


def _deep(
    page_of: Callable[[FeedCursor | None], FeedPage], page: int = DEEP_PAGE
) -> FeedCursor | None:
    cursor: FeedCursor | None = None
    for _ in range(page - 1):
        cursor = page_of(cursor).next_cursor
        assert cursor is not None
    return cursor


def _cold(db_path: Path, run: Callable[[SqliteOfferQueries], object], name: str) -> None:
    """First call on a fresh connection (cold page cache and statement cache)."""
    fresh = connect(db_path)
    try:
        start = time.perf_counter()
        run(SqliteOfferQueries(fresh))
        elapsed = time.perf_counter() - start
    finally:
        fresh.close()
    print(f"{name} (cold): {elapsed * 1000:.1f} ms")
    assert elapsed < BOUND_S, f"{name} cold: {elapsed * 1000:.1f} ms"


def _check(
    conn: sqlite3.Connection,
    run: Callable[[], FeedPage],
    name: str,
    *,
    sorts_ok: bool = False,
) -> float:
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        page = run()
    finally:
        conn.set_trace_callback(None)
    assert page.cards, f"{name}: empty page, the scenario tests nothing"
    for sql in (s for s in statements if s.lstrip().upper().startswith("SELECT")):
        for row in conn.execute("EXPLAIN QUERY PLAN " + sql):
            assert not _FULL_SCAN.match(row[3]), f"{name}: {row[3]}"
            if not (
                name.startswith("search") or sorts_ok
            ):  # the index already gives the page its order
                assert "TEMP B-TREE" not in row[3] or "ORDER BY" not in row[3], f"{name}: {row[3]}"
    run()  # warm-up
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        run()
        timings.append(time.perf_counter() - start)
    median = statistics.median(timings)
    print(f"{name}: {median * 1000:.1f} ms")
    assert median < BOUND_S, f"{name}: {median * 1000:.1f} ms"
    return median


@pytest.mark.slow
def test_volume_feed_pages(conn: sqlite3.Connection) -> None:
    q = SqliteOfferQueries(conn)
    _check(conn, lambda: q.feed(NOTHING, None), "feed first page")
    cursor = _deep(lambda cur: q.feed(NOTHING, cur))
    _check(conn, lambda: q.feed(NOTHING, cursor), "feed 100th page")


@pytest.mark.slow
def test_volume_feed_with_store_and_price_filters(conn: sqlite3.Connection) -> None:
    q = SqliteOfferQueries(conn)
    flt = FeedFilter(None, 5000, 60000, ("amazon", "kabum"), True, None)
    _check(conn, lambda: q.feed(flt, None), "filtered feed first page")
    cursor = _deep(lambda cur: q.feed(flt, cur))
    _check(conn, lambda: q.feed(flt, cursor), "filtered feed 100th page")


@pytest.mark.slow
def test_volume_coupons_pages(conn: sqlite3.Connection) -> None:
    q = SqliteOfferQueries(conn)
    flt = CouponFilter()
    _check(conn, lambda: q.coupons(flt, None), "coupons first page")
    cursor = _deep(lambda cur: q.coupons(flt, cur))
    _check(conn, lambda: q.coupons(flt, cursor), "coupons 100th page")
    since = CouponFilter(stores=("shopee",), since=T0 + timedelta(hours=100))
    _check(conn, lambda: q.coupons(since, None), "coupons store+since")


@pytest.mark.slow
def test_volume_fts_search(conn: sqlite3.Connection) -> None:
    q = SqliteOfferQueries(conn)
    for term in ("raro", "marca42", "produto"):
        flt = FeedFilter(term, None, None, (), False, None)
        _check(conn, lambda flt=flt: q.feed(flt, None), f"search '{term}'")


@pytest.mark.slow
def test_volume_feed_with_rare_channel_and_narrow_price_filters(
    conn: sqlite3.Connection, db_path: Path
) -> None:
    q = SqliteOfferQueries(conn)
    channel = FeedFilter(None, None, None, (), False, 7)
    _check(conn, lambda: q.feed(channel, None), "channel feed first page")
    cursor = _deep(lambda cur: q.feed(channel, cur), 50)  # one channel holds ~2,500 offers
    _check(conn, lambda: q.feed(channel, cursor), "channel feed 50th page")
    rare = FeedFilter(None, None, None, ("magalu",), False, 7)
    _check(conn, lambda: q.feed(rare, None), "channel+store feed first page")
    narrow = FeedFilter(None, 5000, 5400, (), True, None)  # a few hundred rows match
    _check(conn, lambda: q.feed(narrow, None), "narrow price first page", sorts_ok=True)
    _cold(db_path, lambda f: f.feed(channel, None), "channel feed first page")
    _cold(db_path, lambda f: f.feed(narrow, None), "narrow price first page")


@pytest.mark.slow
def test_volume_cold_first_calls(db_path: Path, conn: sqlite3.Connection) -> None:
    assert conn  # the fixture seeds the file
    _cold(db_path, lambda f: f.feed(NOTHING, None), "feed first page")
    _cold(db_path, lambda f: f.coupons(CouponFilter(), None), "coupons first page")
    _cold(db_path, lambda f: f.matches_page(1, None), "matches first page")


@pytest.mark.slow
def test_volume_matches_page_with_20k_matches_on_one_wish(conn: sqlite3.Connection) -> None:
    q = SqliteOfferQueries(conn)
    count = conn.execute("SELECT COUNT(*) FROM offer_matches WHERE wish_id = 1").fetchone()[0]
    assert count >= 20_000

    def page_of(cursor: FeedCursor | None) -> FeedPage:
        cards, nxt = q.matches_page(1, cursor)
        return FeedPage(tuple(m.card for m in cards), nxt)

    _check(conn, lambda: page_of(None), "matches first page")
    cursor = _deep(page_of)
    _check(conn, lambda: page_of(cursor), "matches 100th page")


@pytest.mark.slow
def test_volume_feed_collapse_uses_indexes_and_enriched_cards(conn: sqlite3.Connection) -> None:
    q = SqliteOfferQueries(conn)
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        page = q.feed(NOTHING, None)
    finally:
        conn.set_trace_callback(None)
    assert page.cards
    feed_sql = next(s for s in statements if "px.store" in s)
    plan = [row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + feed_sql)]
    assert any(line.startswith("SEARCH px") and "INDEX" in line for line in plan), plan
    assert any(line.startswith("SEARCH x") and "INDEX" in line for line in plan), plan
    deep = _deep(lambda cur: q.feed(NOTHING, cur))
    page = q.feed(NOTHING, deep)
    assert page.cards
    assert any(c.image_url for c in q.feed(NOTHING, None, 200).cards)


@pytest.mark.slow
def test_volume_product_summaries_and_keyed_matches(conn: sqlite3.Connection) -> None:
    q = SqliteOfferQueries(conn)
    now = T0 + timedelta(days=400)
    timings = []
    for name, run in (
        ("product()", lambda: q.product(1, now, None, None)),
        ("summaries x20", lambda: q.summaries(list(range(1, 21)))),
        ("matches_page keyed", lambda: q.matches_page(1, None, 30, dominant=("amazon", "P0"))),
    ):
        run()  # warm-up
        runs = []
        for _ in range(3):
            start = time.perf_counter()
            run()
            runs.append(time.perf_counter() - start)
        median = statistics.median(runs)
        timings.append(median)
        print(f"{name}: {median * 1000:.1f} ms")
        assert median < BOUND_S, f"{name}: {median * 1000:.1f} ms"
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        SqliteOfferRepository(conn).dominant_key(1)
    finally:
        conn.set_trace_callback(None)
    sql = next(s for s in statements if "GROUP BY" in s)
    for row in conn.execute("EXPLAIN QUERY PLAN " + sql):
        assert not _FULL_SCAN.match(row[3]), row[3]


@pytest.mark.slow
def test_volume_stale_cursor_count_is_capped_and_fast(conn: sqlite3.Connection) -> None:
    q = SqliteOfferQueries(conn)
    stale = FeedCursor(T0 - timedelta(days=1), 0, 0)  # everything in the feed is newer
    start = time.perf_counter()
    count = q.count_feed_after(NOTHING, stale)
    elapsed = time.perf_counter() - start
    print(f"count_feed_after stale cursor: {elapsed * 1000:.1f} ms")
    assert count == NEWS_COUNT_CAP
    assert elapsed < BOUND_S, f"{elapsed * 1000:.1f} ms"


@pytest.mark.slow
def test_volume_five_hot_products_first_page(tmp_path: Path) -> None:
    """Extreme skew: five products hold half of the offers; the collapse probe must stay fast."""
    c = connect(tmp_path / "hot.db")
    apply_migrations(c, MIGRATION_PACKAGES)
    stamp = to_iso(T0)
    rows = []
    for i in range(ROWS):
        at = to_iso(T0 + timedelta(seconds=30 * i))
        link = f"https://hot.test/p{i % 5}" if i % 2 == 0 else f"https://cold.test/p{i}"
        rows.append((i % 20, i, at, f"Produto {i}", 1000 + i % 50, "amazon", link, at))
    with c:
        c.executemany(
            "INSERT INTO product_links (url, store, product_id, kind, status, created_at, "
            "offer_posted_at, host) VALUES (?,?,?,'product','done',?,?,'hot.test')",
            [(f"https://hot.test/p{n}", "amazon", f"H{n}", stamp, stamp) for n in range(5)],
        )
        c.executemany(
            "INSERT INTO offers (channel_id, message_id, posted_at, title, price_cents, store, "
            "main_link, has_photo, sold_out, deleted, updated_at) "
            "VALUES (?,?,?,?,?,?,?,0,0,0,?)",
            rows,
        )
    c.execute("ANALYZE")
    q = SqliteOfferQueries(c)
    try:
        _check(c, lambda: q.feed(NOTHING, None), "five hot products first page")
    finally:
        c.close()
