import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.repositories import (
    FakeMessageSource,
    FakeWishReader,
    InMemoryLinkRepository,
    InMemoryOfferRepository,
)
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.offers import OfferBuilder, SourceMessage, rebuild_offers
from velkgram.offers.adapters.sqlite.links import SqliteLinkRepository
from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository
from velkgram.offers.domain.models import Offer
from velkgram.offers.ports.links import LinkRepository, LinkRow
from velkgram.offers.ports.repository import OfferRepository
from velkgram.shared.db import connect
from velkgram.shared.events import MessageData
from velkgram.shared.migrate import apply_migrations

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
NO_HOSTS: frozenset[str] = frozenset()


@dataclass
class Handle:
    offers: OfferRepository
    links: LinkRepository


@pytest.fixture(params=["memory", "sqlite"])
def handle(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Handle]:
    if request.param == "memory":
        offers = InMemoryOfferRepository()
        yield Handle(offers, InMemoryLinkRepository(offers))
        return
    conn: sqlite3.Connection = connect(tmp_path / "t.db")
    apply_migrations(conn, MIGRATION_PACKAGES)
    yield Handle(SqliteOfferRepository(conn), SqliteLinkRepository(conn))
    conn.close()


def _offer(message_id: int, link: str | None, **kw: object) -> Offer:
    base = Offer(
        channel_id=10,
        message_id=message_id,
        posted_at=T0 + timedelta(minutes=message_id),
        title="SSD Kingston 1TB",
        price_cents=29990,
        store=None,
        main_link=link,
        has_photo=False,
        text="SSD Kingston 1TB R$ 299,90",
        norm_text="ssd kingston 1tb r$ 299,90",
        origin_channel_id=None,
        origin_message_id=None,
        sold_out=False,
        deleted=False,
        updated_at=T0,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def _discovered(h: Handle, url: str) -> LinkRow:
    h.links.discover()
    row = h.links.next_due(T0 + timedelta(days=30), NO_HOSTS)
    assert row is not None and row.url == url
    return row


def _done(row: LinkRow, **kw: object) -> LinkRow:
    base = replace(row, status="done", kind="product", fetched_at=T0)
    return replace(base, **kw)  # type: ignore[arg-type]


def test_discover_is_idempotent_and_respects_the_limit(handle: Handle) -> None:
    handle.offers.upsert(_offer(1, "https://a.example/1"))
    handle.offers.upsert(_offer(3, "https://b.example/1"))
    handle.offers.upsert(_offer(2, "https://c.example/1"))
    assert handle.links.discover(limit=2) == 2
    assert handle.links.discover(limit=2) == 1
    assert handle.links.discover() == 0


def test_discover_picks_newest_link_first(handle: Handle) -> None:
    handle.offers.upsert(_offer(1, "https://old.example/1"))
    handle.offers.upsert(_offer(5, "https://new.example/1"))
    handle.links.discover(limit=1)
    row = handle.links.next_due(T0 + timedelta(days=1), NO_HOSTS)
    assert row is not None and row.url == "https://new.example/1"
    assert row.offer_posted_at == T0 + timedelta(minutes=5)
    assert row.host == "new.example"


def test_discover_skips_deleted_and_linkless_offers(handle: Handle) -> None:
    handle.offers.upsert(_offer(1, "https://gone.example/1", deleted=True))
    handle.offers.upsert(_offer(2, None))
    assert handle.links.discover() == 0


def test_discover_gives_one_row_for_a_link_shared_by_three_offers(handle: Handle) -> None:
    for mid in (1, 2, 3):
        handle.offers.upsert(_offer(mid, "https://shared.example/x"))
    assert handle.links.discover() == 1
    row = handle.links.next_due(T0 + timedelta(days=1), NO_HOSTS)
    assert row is not None and row.offer_posted_at == T0 + timedelta(minutes=3)


def test_next_due_skips_future_retry_and_picks_it_once_due(handle: Handle) -> None:
    handle.offers.upsert(_offer(1, "https://a.example/1"))
    row = _discovered(handle, "https://a.example/1")
    handle.links.save(
        replace(row, attempts=1, next_try_at=T0 + timedelta(hours=1)), fix_store=False
    )
    assert handle.links.next_due(T0, NO_HOSTS) is None
    assert handle.links.next_due(T0 + timedelta(hours=1), NO_HOSTS) is not None


def test_next_due_blocked_only_when_due_and_under_two_blocks(handle: Handle) -> None:
    handle.offers.upsert(_offer(1, "https://a.example/1"))
    row = _discovered(handle, "https://a.example/1")
    due = T0 + timedelta(hours=24)
    handle.links.save(replace(row, status="blocked", blocks=1, next_try_at=due), fix_store=False)
    assert handle.links.next_due(due - timedelta(seconds=1), NO_HOSTS) is None
    assert handle.links.next_due(due, NO_HOSTS) is not None
    handle.links.save(replace(row, status="blocked", blocks=2, next_try_at=due), fix_store=False)
    assert handle.links.next_due(due, NO_HOSTS) is None


def test_next_due_ignores_done_and_failed(handle: Handle) -> None:
    handle.offers.upsert(_offer(1, "https://a.example/1"))
    handle.offers.upsert(_offer(2, "https://b.example/1"))
    handle.links.discover()
    now = T0 + timedelta(days=1)
    for status in ("done", "failed"):
        row = handle.links.next_due(now, NO_HOSTS)
        assert row is not None
        handle.links.save(replace(row, status=status), fix_store=False)  # type: ignore[arg-type]
    assert handle.links.next_due(now, NO_HOSTS) is None


def test_next_due_skips_paused_url_host_and_paused_final_host(handle: Handle) -> None:
    handle.offers.upsert(_offer(1, "https://short.example/a"))
    handle.offers.upsert(_offer(2, "https://other.example/b"))
    handle.links.discover()
    now = T0 + timedelta(days=1)
    first = handle.links.next_due(now, NO_HOSTS)
    assert first is not None and first.url == "https://other.example/b"
    # Paused URL host: the other store still gets served.
    got = handle.links.next_due(now, frozenset({"other.example"}))
    assert got is not None and got.url == "https://short.example/a"
    # Paused final host: the row that resolved there is skipped, the other is served.
    handle.links.save(
        replace(first, final_url="https://big.example/p", attempts=1, next_try_at=T0),
        fix_store=False,
    )
    got = handle.links.next_due(now, frozenset({"big.example"}))
    assert got is not None and got.url == "https://short.example/a"
    assert handle.links.next_due(now, frozenset({"big.example", "short.example"})) is None


def test_next_due_skips_rows_whose_offers_are_all_deleted(handle: Handle) -> None:
    handle.offers.upsert(_offer(1, "https://a.example/1"))
    handle.links.discover()
    handle.offers.mark_deleted(10, [1], T0)
    assert handle.links.next_due(T0 + timedelta(days=1), NO_HOSTS) is None
    assert handle.links.earliest_next_try(T0, NO_HOSTS) is None


def test_earliest_next_try_covers_due_rows_and_ignores_paused(handle: Handle) -> None:
    handle.offers.upsert(_offer(1, "https://a.example/1"))
    handle.offers.upsert(_offer(2, "https://b.example/1"))
    handle.links.discover()
    assert handle.links.earliest_next_try(T0, NO_HOSTS) == T0  # never tried: due now
    a = handle.links.next_due(T0, frozenset({"a.example"}))
    assert a is not None and a.url == "https://b.example/1"
    handle.links.save(
        replace(a, attempts=1, next_try_at=T0 + timedelta(minutes=5)), fix_store=False
    )
    assert handle.links.earliest_next_try(T0, frozenset({"a.example"})) == T0 + timedelta(minutes=5)
    assert handle.links.earliest_next_try(T0, frozenset({"a.example", "b.example"})) is None


def test_known_product_returns_title_and_image_of_a_done_row(handle: Handle) -> None:
    handle.offers.upsert(_offer(1, "https://a.example/1"))
    row = _discovered(handle, "https://a.example/1")
    assert handle.links.known_product("amazon", "B0X") is None
    pending = replace(row, store="amazon", product_id="B0X", title="Fone", image_url="https://i/x")
    handle.links.save(replace(pending, status="pending"), fix_store=False)
    assert handle.links.known_product("amazon", "B0X") is None
    handle.links.save(_done(pending), fix_store=False)
    assert handle.links.known_product("amazon", "B0X") == ("Fone", "https://i/x")
    assert handle.links.known_product("amazon", "B0Y") is None
    handle.links.save(_done(pending, title=None), fix_store=False)
    assert handle.links.known_product("amazon", "B0X") is None


def test_save_fix_store_fills_missing_stores_and_never_overwrites(handle: Handle) -> None:
    link = "https://short.example/a"
    handle.offers.upsert(_offer(1, link))
    handle.offers.upsert(_offer(2, link))
    handle.offers.upsert(_offer(3, link, store="kabum"))
    handle.offers.upsert(_offer(0, "https://other.example/z"))
    row = _discovered(handle, link)
    assert handle.links.save(_done(row, store="amazon"), fix_store=True) == 2
    assert [handle.offers.get(10, m).store for m in (1, 2, 3, 0)] == [  # type: ignore[union-attr]
        "amazon",
        "amazon",
        "kabum",
        None,
    ]
    assert handle.offers.get(10, 1).updated_at == T0  # type: ignore[union-attr]


def test_save_without_fix_store_leaves_offers_alone(handle: Handle) -> None:
    link = "https://short.example/a"
    handle.offers.upsert(_offer(1, link))
    row = _discovered(handle, link)
    assert handle.links.save(_done(row, store="amazon"), fix_store=False) == 0
    assert handle.offers.get(10, 1).store is None  # type: ignore[union-attr]


def test_heartbeat_counts_statuses(handle: Handle) -> None:
    assert handle.links.heartbeat() is None
    for mid, host in enumerate(("a", "b", "c", "d"), start=1):
        handle.offers.upsert(_offer(mid, f"https://{host}.example/1"))
    handle.links.discover()
    for status in ("done", "failed", "blocked"):
        row = handle.links.next_due(T0 + timedelta(days=9), NO_HOSTS)
        assert row is not None
        handle.links.save(
            replace(row, status=status, next_try_at=T0 + timedelta(days=99)), fix_store=False
        )  # type: ignore[arg-type]
    handle.links.write_heartbeat(T0)
    hb = handle.links.heartbeat()
    assert hb is not None
    assert (hb.last_run_at, hb.pending, hb.done, hb.failed, hb.blocked) == (T0, 1, 1, 1, 1)
    handle.links.write_heartbeat(T0 + timedelta(minutes=1))
    hb = handle.links.heartbeat()
    assert hb is not None and hb.last_run_at == T0 + timedelta(minutes=1)


# --- A store fixed by the enricher survives every way an offer is rewritten. ---

LINK = "https://bit.ly/short"


def _fixed(h: Handle) -> None:
    h.offers.upsert(_offer(1, LINK))
    row = _discovered(h, LINK)
    assert h.links.save(_done(row, store="amazon"), fix_store=True) == 1


def _store(h: Handle) -> str | None:
    o = h.offers.get(10, 1)
    assert o is not None
    return o.store


def test_fixed_store_survives_upsert_of_the_same_message(handle: Handle) -> None:
    _fixed(handle)
    handle.offers.upsert(_offer(1, LINK))
    assert _store(handle) == "amazon"


def test_fixed_store_survives_an_edit(handle: Handle) -> None:
    _fixed(handle)
    handle.offers.upsert(_offer(1, LINK, title="Novo titulo", price_cents=19990))
    assert _store(handle) == "amazon"


def test_fixed_store_survives_a_blank_redelivery(handle: Handle) -> None:
    _fixed(handle)
    handle.offers.upsert(_offer(1, LINK, text=None, norm_text=None, title=""))
    assert _store(handle) == "amazon"


def test_fixed_store_survives_rebuild_offers(handle: Handle) -> None:
    _fixed(handle)
    msg = MessageData(
        10, 1, T0, T0, "SSD Kingston 1TB por R$ 299,90", (LINK,), None, None, None, True, "backfill"
    )
    builder = OfferBuilder(handle.offers, FakeWishReader(), FakeClock(T0))
    assert rebuild_offers(FakeMessageSource([SourceMessage(msg, False, False)]), builder) == 1
    built = handle.offers.get(10, 1)
    assert built is not None and built.main_link == LINK
    assert built.store == "amazon"


def test_fixed_store_and_link_rows_survive_text_purge(handle: Handle) -> None:
    _fixed(handle)
    assert handle.offers.purge_text_before(T0 + timedelta(days=1)) == 1
    assert _store(handle) == "amazon"
    assert handle.links.known_product("amazon", "x") is None
    assert handle.links.earliest_next_try(T0, NO_HOSTS) is None  # done row still there, not due
    assert handle.links.discover() == 0  # and it is not rediscovered
