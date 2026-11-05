import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tests.offers.adapters._queries_helpers import T0, match, offer, put
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.offers.adapters.sqlite.queries import SqliteOfferQueries
from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository
from velkgram.offers.domain.models import MatchSource, RetroRun, RetroStatus
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

NOW = T0 + timedelta(days=400)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, MIGRATION_PACKAGES)
    yield c
    c.close()


def _add(conn: sqlite3.Connection, wish_id: int, mid: int, at: datetime, price: int | None) -> None:
    o = offer(mid, at=at, price=price)
    put(conn, o)
    SqliteOfferRepository(conn).add_match(match(wish_id, o))


def test_product_points_are_daily_minimum_and_capped_at_200(conn: sqlite3.Connection) -> None:
    _add(conn, 1, 1, T0, 500)
    _add(conn, 1, 2, T0 + timedelta(hours=2), 300)
    _add(conn, 1, 3, T0 + timedelta(days=1), 400)
    q = SqliteOfferQueries(conn)
    pts = q.product(1, NOW, None, None).points
    assert [p.price_cents for p in pts] == [300, 400]
    assert pts[0].posted_at.date() == T0.date()

    for d in range(2, 260):
        _add(conn, 1, 100 + d, T0 + timedelta(days=d), 1000 + d)
    pts = q.product(1, NOW, None, None).points
    assert len(pts) == 200
    assert pts[-1].posted_at.date() == (T0 + timedelta(days=259)).date()
    assert [p.posted_at for p in pts] == sorted(p.posted_at for p in pts)
    assert pts[0].price_cents == 300  # first bucket keeps the lowest price


def test_product_points_respect_range_and_skip_unknown_prices(conn: sqlite3.Connection) -> None:
    now = T0 + timedelta(days=100)
    _add(conn, 1, 1, now - timedelta(days=50), 100)
    _add(conn, 1, 2, now - timedelta(days=5), 200)
    _add(conn, 1, 3, now - timedelta(days=4), None)
    pts = SqliteOfferQueries(conn).product(1, now, 30, None).points
    assert [p.price_cents for p in pts] == [200]


def test_product_stats_use_all_matches(conn: sqlite3.Connection) -> None:
    now = T0 + timedelta(days=100)
    _add(conn, 1, 1, now - timedelta(days=50), 100)
    _add(conn, 1, 2, now - timedelta(days=5), 200)
    _add(conn, 1, 3, now - timedelta(days=4), None)
    h = SqliteOfferQueries(conn).product(1, now, 7, None)
    assert h.stats.lowest_cents == 100
    assert h.stats.match_count == 3
    assert h.stats.last_cents == 200
    assert h.stats.avg_30d_cents == 200


def test_product_matches_paginate_with_source(conn: sqlite3.Connection) -> None:
    for i in range(1, 6):
        o = offer(i, price=100 * i)
        put(conn, o)
        src = MatchSource.retro if i % 2 else MatchSource.live
        SqliteOfferRepository(conn).add_match(match(1, o, src))
    q = SqliteOfferQueries(conn)
    p1 = q.product(1, NOW, None, None, limit=2)
    assert [m.card.message_id for m in p1.matches] == [5, 4]
    assert [m.source for m in p1.matches] == [MatchSource.retro, MatchSource.live]
    assert p1.matches[0].matched_price_cents == 500
    p2 = q.product(1, NOW, None, p1.next_cursor, limit=2)
    assert [m.card.message_id for m in p2.matches] == [3, 2]
    p3 = q.product(1, NOW, None, p2.next_cursor, limit=2)
    assert [m.card.message_id for m in p3.matches] == [1]
    assert p3.next_cursor is None


def test_product_includes_retro_run(conn: sqlite3.Connection) -> None:
    q = SqliteOfferQueries(conn)
    assert q.product(1, NOW, None, None).retro is None
    run = RetroRun(1, "fp", RetroStatus.done, T0, T0, None)
    SqliteOfferRepository(conn).save_retro_run(run)
    assert q.product(1, NOW, None, None).retro == run
    assert q.product(1, NOW, None, None).stats.match_count == 0


def test_summaries_last_price_count_and_recent_prices(conn: sqlite3.Connection) -> None:
    for i in range(1, 36):
        _add(conn, 1, i, T0 + timedelta(hours=i), 1000 + i)
    _add(conn, 1, 99, T0 + timedelta(hours=99), None)
    _add(conn, 2, 200, T0, None)
    s = SqliteOfferQueries(conn).summaries([1, 2, 3])
    assert s[1].match_count == 36
    assert s[1].last_cents == 1035
    assert s[1].recent_prices == tuple(range(1006, 1036))
    assert s[2].last_cents is None and s[2].recent_prices == () and s[2].match_count == 1
    assert s[3].match_count == 0


def test_stores_seen(conn: sqlite3.Connection) -> None:
    put(conn, offer(1, store="kabum"), offer(2, store="amazon"), offer(3, store=None))
    put(conn, offer(4, store="amazon"))
    assert SqliteOfferQueries(conn).stores_seen() == ["amazon", "kabum"]
