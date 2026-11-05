import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.fakes.repositories import InMemoryOfferRepository
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository
from velkgram.offers.domain.models import (
    CouponTier,
    MatchSource,
    Offer,
    OfferKind,
    OfferMatch,
    RetroRun,
    RetroStatus,
)
from velkgram.offers.ports.repository import OfferRepository
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


@dataclass
class Handle:
    repo: OfferRepository
    conn: sqlite3.Connection | None = None


@pytest.fixture(params=["memory", "sqlite"])
def handle(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Handle]:
    if request.param == "memory":
        yield Handle(InMemoryOfferRepository())
        return
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, MIGRATION_PACKAGES)
    yield Handle(SqliteOfferRepository(conn), conn)
    conn.close()


def _offer(message_id: int = 1, channel_id: int = 10, **kw: object) -> Offer:
    base = Offer(
        channel_id=channel_id,
        message_id=message_id,
        posted_at=T0,
        title="SSD Kingston 1TB",
        price_cents=29990,
        store="amazon",
        main_link="https://amzn.to/x",
        has_photo=True,
        text="SSD Kingston 1TB R$ 299,90",
        norm_text="ssd kingston 1tb r$ 299,90",
        origin_channel_id=5,
        origin_message_id=6,
        sold_out=False,
        deleted=False,
        updated_at=T0,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def _match(
    wish_id: int = 1, message_id: int = 1, posted_at: datetime = T0, **kw: object
) -> OfferMatch:
    base = OfferMatch(wish_id, 10, message_id, 100, posted_at, MatchSource.live, T0)
    return replace(base, **kw)  # type: ignore[arg-type]


def test_upsert_then_get_round_trips(handle: Handle) -> None:
    o = _offer()
    handle.repo.upsert(o)
    assert handle.repo.get(10, 1) == o
    assert handle.repo.get(10, 2) is None


def test_upsert_replaces_existing(handle: Handle) -> None:
    handle.repo.upsert(_offer())
    changed = _offer(title="Outro", price_cents=None, text=None, norm_text=None, sold_out=True)
    handle.repo.upsert(changed)
    assert handle.repo.get(10, 1) == changed


def test_coupon_fields_round_trip_and_upsert_updates_them(handle: Handle) -> None:
    coupon = _offer(
        title="Cupom Shopee",
        price_cents=None,
        comparable=False,
        kind=OfferKind.coupon,
        coupons=("QIP98Q1ZXO", "ZAFADINHO10"),
        coupon_discount="R$ 10 OFF",
        coupon_min_cents=4000,
        coupon_scope="Selecionados",
        coupon_tiers=(
            CouponTier("R$ 10 OFF", 4000),
            CouponTier("10% OFF", 7900, 4000, ("SEMPRESAUDE", "PROMOSML")),
        ),
        redeem_link="https://s.shopee.com.br/a",
        cart_link="https://s.shopee.com.br/b",
    )
    handle.repo.upsert(coupon)
    assert handle.repo.get(10, 1) == coupon
    plain = _offer(title="Cupom Shopee")
    handle.repo.upsert(plain)
    assert handle.repo.get(10, 1) == plain


def test_mark_deleted(handle: Handle) -> None:
    handle.repo.upsert(_offer(1))
    handle.repo.upsert(_offer(2))
    handle.repo.upsert(_offer(3))
    handle.repo.mark_deleted(10, [1, 2], T0 + timedelta(hours=1))
    one, two, three = (handle.repo.get(10, i) for i in (1, 2, 3))
    assert one is not None and one.deleted and one.updated_at == T0 + timedelta(hours=1)
    assert two is not None and two.deleted
    assert three is not None and not three.deleted


def test_add_match_false_when_duplicate(handle: Handle) -> None:
    assert handle.repo.add_match(_match()) is True
    assert handle.repo.add_match(_match()) is False


def test_add_matches_inserts_batch_and_skips_duplicates(handle: Handle) -> None:
    handle.repo.add_match(_match(message_id=1))
    n = handle.repo.add_matches([_match(message_id=1), _match(message_id=2), _match(message_id=3)])
    assert n == 2
    assert len(handle.repo.priced_points(1)) == 3


def test_delete_matches_since_keeps_older(handle: Handle) -> None:
    handle.repo.add_match(_match(message_id=1, posted_at=T0))
    handle.repo.add_match(_match(message_id=2, posted_at=T0 + timedelta(days=1)))
    handle.repo.add_match(_match(wish_id=2, message_id=1))
    assert handle.repo.delete_matches(1, T0 + timedelta(hours=1)) == 1
    assert [p[0] for p in handle.repo.priced_points(1)] == [T0]
    assert len(handle.repo.priced_points(2)) == 1


def test_delete_matches_none_deletes_all(handle: Handle) -> None:
    handle.repo.add_match(_match(message_id=1))
    handle.repo.add_match(_match(message_id=2))
    assert handle.repo.delete_matches(1, None) == 2
    assert handle.repo.priced_points(1) == []


def test_priced_points_oldest_first_includes_unknown(handle: Handle) -> None:
    handle.repo.add_match(_match(message_id=1, posted_at=T0 + timedelta(days=1), price_cents=5))
    handle.repo.add_match(_match(message_id=2, posted_at=T0, price_cents=None))
    assert handle.repo.priced_points(1) == [(T0, None), (T0 + timedelta(days=1), 5)]


def test_iter_offers_with_text_batches_ordered(handle: Handle) -> None:
    for i in (5, 3, 1, 4, 2):
        handle.repo.upsert(_offer(i, posted_at=T0 + timedelta(minutes=i)))
    handle.repo.upsert(_offer(9, posted_at=T0 - timedelta(days=5)))
    batches = list(handle.repo.iter_offers_with_text(T0, 2))
    assert [len(b) for b in batches] == [2, 2, 1]
    assert [t.message_id for b in batches for t in b] == [1, 2, 3, 4, 5]
    first = batches[0][0]
    assert (first.channel_id, first.price_cents, first.norm_text) == (
        10,
        29990,
        "ssd kingston 1tb r$ 299,90",
    )
    assert first.posted_at == T0 + timedelta(minutes=1)


def test_iter_skips_null_text_and_deleted(handle: Handle) -> None:
    handle.repo.upsert(_offer(1))
    handle.repo.upsert(_offer(2, text=None, norm_text=None))
    handle.repo.upsert(_offer(3, deleted=True))
    ids = [t.message_id for b in handle.repo.iter_offers_with_text(T0, 10) for t in b]
    assert ids == [1]


def test_purge_text_before_counts_and_is_idempotent(handle: Handle) -> None:
    handle.repo.upsert(_offer(1, posted_at=T0 - timedelta(days=100)))
    handle.repo.upsert(_offer(2, posted_at=T0))
    assert handle.repo.purge_text_before(T0 - timedelta(days=1)) == 1
    assert handle.repo.purge_text_before(T0 - timedelta(days=1)) == 0
    old = handle.repo.get(10, 1)
    assert old is not None and old.text is None and old.norm_text is None
    new = handle.repo.get(10, 2)
    assert new is not None and new.text is not None


def _run(wish_id: int = 1, **kw: object) -> RetroRun:
    base = RetroRun(wish_id, "abc", RetroStatus.running, T0, None, None)
    return replace(base, **kw)  # type: ignore[arg-type]


def test_retro_run_save_get_list(handle: Handle) -> None:
    assert handle.repo.get_retro_run(1) is None
    handle.repo.save_retro_run(_run(1))
    handle.repo.save_retro_run(_run(2))
    done = _run(1, status=RetroStatus.done, finished_at=T0 + timedelta(seconds=3))
    handle.repo.save_retro_run(done)
    assert handle.repo.get_retro_run(1) == done
    failed = _run(2, status=RetroStatus.failed, error="boom")
    handle.repo.save_retro_run(failed)
    assert sorted(handle.repo.list_retro_runs(), key=lambda r: r.wish_id) == [done, failed]


def test_delete_retro_run_keeps_matches(handle: Handle) -> None:
    handle.repo.save_retro_run(_run(1))
    handle.repo.add_match(_match())
    handle.repo.delete_retro_run(1)
    assert handle.repo.get_retro_run(1) is None
    assert len(handle.repo.priced_points(1)) == 1


def test_delete_wish_data(handle: Handle) -> None:
    handle.repo.save_retro_run(_run(1))
    handle.repo.add_match(_match())
    handle.repo.add_match(_match(wish_id=2))
    handle.repo.delete_wish_data(1)
    assert handle.repo.get_retro_run(1) is None
    assert handle.repo.priced_points(1) == []
    assert len(handle.repo.priced_points(2)) == 1


def test_upsert_twice_reindexes_fts(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, MIGRATION_PACKAGES)
    repo = SqliteOfferRepository(conn)
    repo.upsert(_offer(title="t", text="kingston", norm_text="kingston"))
    id_before = conn.execute("SELECT id FROM offers").fetchone()[0]
    repo.upsert(_offer(title="t", text="samsung", norm_text="samsung"))

    def hits(term: str) -> int:
        q = "SELECT rowid FROM offers_fts WHERE offers_fts MATCH ?"
        return len(conn.execute(q, (term,)).fetchall())

    assert hits("kingston") == 0
    assert hits("samsung") == 1
    assert conn.execute("SELECT id FROM offers").fetchone()[0] == id_before
    conn.close()
