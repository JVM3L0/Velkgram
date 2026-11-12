import sqlite3
import statistics
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from tests.offers.adapters._queries_helpers import T0
from tests.timing import within
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.offers.adapters.sqlite.queries import SqliteOfferQueries
from velkgram.offers.adapters.sqlite.repository import to_iso
from velkgram.offers.ports.queries import FeedFilter
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

ROWS = 200_000


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, MIGRATION_PACKAGES)
    yield c
    c.close()


@pytest.mark.slow
def test_feed_first_page_under_300ms_with_200k_offers(conn: sqlite3.Connection) -> None:
    stores = ("amazon", "kabum", "magalu", None)
    rows = []
    for i in range(ROWS):
        at = to_iso(T0 + timedelta(seconds=30 * i))
        fwd = i % 7 == 0
        rows.append(
            (
                i % 20,
                i,
                at,
                f"Produto {i}",
                (i * 37) % 100000 or None,
                stores[i % 4],
                f"https://x.test/p{i % 5000}",
                i % 2,
                f"Produto {i} texto de oferta",
                f"produto {i} texto de oferta",
                (i + 1) % 20 if fwd else None,
                i - 1 if fwd else None,
                0,
                0,
                at,
            )
        )
    stamp = to_iso(T0)
    with conn:
        conn.executemany(  # half of the links enriched, so the collapse EXISTS does real work
            "INSERT INTO product_links (url, store, product_id, kind, status, created_at, "
            "offer_posted_at, host) VALUES (?,?,?,'product','done',?,?,'x.test')",
            [
                (f"https://x.test/p{n}", stores[n % 4], f"P{n % 1250}", stamp, stamp)
                for n in range(0, 5000, 2)
            ],
        )
        conn.executemany(
            "INSERT INTO offers (channel_id, message_id, posted_at, title, price_cents, store, "
            "main_link, has_photo, text, norm_text, origin_channel_id, origin_message_id, "
            "sold_out, deleted, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    q = SqliteOfferQueries(conn)
    f = FeedFilter(None, None, None, (), False, None)
    timings = []
    page = q.feed(f, None)  # warm-up, also gives `page` a value
    for _ in range(3):
        start = time.perf_counter()
        page = q.feed(f, None)
        timings.append(time.perf_counter() - start)
    assert len(page.cards) == 30
    bound = 0.3
    print(f"feed first page timings (s): {timings}")
    within(statistics.median(timings), bound, "feed first page")
