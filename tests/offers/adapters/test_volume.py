"""Volume check: 50,000 offers (and their messages) must page and search fast.

Every timed read must finish under 150 ms and must not `SCAN offers` without an index; the
plan check runs EXPLAIN QUERY PLAN on the statements the query port really executed.

Measured on the dev machine (WSL2, median of 3 runs after a warm-up), migration 004 applied:
feed first page 0.2 ms, 100th page 0.2 ms; filtered feed 0.3 ms / 0.3 ms; coupons first page
0.3 ms, 100th page 0.3 ms, store+since 0.3 ms; FTS search
"raro" 3.2 ms, "marca42" 0.5 ms, "produto" (matches nearly everything) 5.4 ms.
"""

import json
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
from velkgram.offers.adapters.sqlite.repository import to_iso
from velkgram.offers.ports.queries import CouponFilter, FeedCursor, FeedFilter, FeedPage
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

ROWS = 50_000
BOUND_S = 0.150
DEEP_PAGE = 100
STORES = ("amazon", "kabum", "magalu", "shopee", None)
NOTHING = FeedFilter(None, None, None, (), False, None)

_FULL_SCAN = re.compile(r"^SCAN (offers|o|r|x)\b(?!.*\bINDEX\b)")


@pytest.fixture(scope="module")
def conn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[sqlite3.Connection]:
    path: Path = tmp_path_factory.mktemp("volume") / "t.db"
    c = connect(path)
    apply_migrations(c, MIGRATION_PACKAGES)
    offers = []
    messages = []
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
                "https://x.test/p",
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
    with c:
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
    yield c
    c.close()


def _deep(page_of: Callable[[FeedCursor | None], FeedPage]) -> FeedCursor | None:
    cursor: FeedCursor | None = None
    for _ in range(DEEP_PAGE - 1):
        cursor = page_of(cursor).next_cursor
        assert cursor is not None
    return cursor


def _check(conn: sqlite3.Connection, run: Callable[[], FeedPage], name: str) -> float:
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
            if not name.startswith("search"):  # the index already gives the page its order
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
