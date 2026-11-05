import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.offers.adapters._queries_helpers import T0, match, offer, put
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.offers.adapters.sqlite.queries import SqliteOfferQueries
from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository
from velkgram.offers.domain.models import OfferKind
from velkgram.offers.ports.queries import CouponFilter, FeedCursor, FeedFilter
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

NOTHING = FeedFilter(None, None, None, (), False, None)
KEYS = [(c, m) for c in (1, 2, 3) for m in range(1, 21)]  # 60 rows
TIES = [T0, T0, T0, T0.replace(minute=5)]  # most rows share a posted_at, across any boundary


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, MIGRATION_PACKAGES)
    yield c
    c.close()


def _walk(
    fetch: Callable[[FeedCursor | None, int], tuple[list[tuple[int, int]], FeedCursor | None]],
    limit: int,
) -> list[tuple[int, int]]:
    seen: list[tuple[int, int]] = []
    cursor: FeedCursor | None = None
    for _ in range(100):
        keys, cursor = fetch(cursor, limit)
        seen.extend(keys)
        if cursor is None:
            return seen
    raise AssertionError("pagination never ended")


@pytest.mark.parametrize("limit", [1, 7, 30])
def test_feed_pages_every_row_once_with_identical_posted_at(
    conn: sqlite3.Connection, limit: int
) -> None:
    put(conn, *(offer(m, channel_id=c, at=TIES[m % 4]) for c, m in KEYS))
    q = SqliteOfferQueries(conn)

    def fetch(cur: FeedCursor | None, n: int) -> tuple[list[tuple[int, int]], FeedCursor | None]:
        page = q.feed(NOTHING, cur, n)
        return [(c.channel_id, c.message_id) for c in page.cards], page.next_cursor

    seen = _walk(fetch, limit)
    assert len(seen) == len(set(seen)) == len(KEYS) and set(seen) == set(KEYS)


@pytest.mark.parametrize("limit", [1, 7, 30])
def test_coupons_page_every_row_once_with_identical_posted_at(
    conn: sqlite3.Connection, limit: int
) -> None:
    put(conn, *(offer(m, channel_id=c, at=TIES[m % 4], kind=OfferKind.coupon) for c, m in KEYS))
    q = SqliteOfferQueries(conn)

    def fetch(cur: FeedCursor | None, n: int) -> tuple[list[tuple[int, int]], FeedCursor | None]:
        page = q.coupons(CouponFilter(), cur, n)
        return [(c.channel_id, c.message_id) for c in page.cards], page.next_cursor

    seen = _walk(fetch, limit)
    assert len(seen) == len(set(seen)) == len(KEYS) and set(seen) == set(KEYS)


@pytest.mark.parametrize("limit", [1, 7, 30])
def test_product_matches_page_every_row_once_with_identical_posted_at(
    conn: sqlite3.Connection, limit: int
) -> None:
    offers = [offer(m, channel_id=c, at=TIES[m % 4]) for c, m in KEYS]
    put(conn, *offers)
    repo = SqliteOfferRepository(conn)
    for o in offers:
        repo.add_match(match(1, o))
    q = SqliteOfferQueries(conn)

    def fetch(cur: FeedCursor | None, n: int) -> tuple[list[tuple[int, int]], FeedCursor | None]:
        history = q.product(1, T0, None, cur, n)
        return [
            (m.card.channel_id, m.card.message_id) for m in history.matches
        ], history.next_cursor

    seen = _walk(fetch, limit)
    assert len(seen) == len(set(seen)) == len(KEYS) and set(seen) == set(KEYS)
