"""Same-product comparison and history across stores, over the stored model codes."""

import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from tests.offers.adapters._queries_helpers import T0, offer, put
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.offers.adapters.sqlite.queries import SqliteOfferQueries
from velkgram.offers.domain.models import OfferKind
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

AOC = 'Monitor Gamer Curvo Aoc Gaming U34g4c 34" Wqhd 180Hz'
NOW = T0 + timedelta(days=3)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, MIGRATION_PACKAGES)
    yield c
    c.close()


def _codes(conn: sqlite3.Connection, message_id: int, channel_id: int = 1) -> list[str]:
    rows = conn.execute(
        "SELECT code FROM offer_codes WHERE channel_id = ? AND message_id = ? ORDER BY code",
        (channel_id, message_id),
    ).fetchall()
    return [r[0] for r in rows]


# --- stored codes ------------------------------------------------------------------------------


def test_upsert_stores_the_model_codes_of_a_product_title(conn: sqlite3.Connection) -> None:
    put(conn, offer(1, title=AOC))
    assert _codes(conn, 1) == ["U34G4C"]


def test_upsert_replaces_the_codes_when_the_title_changes(conn: sqlite3.Connection) -> None:
    put(conn, offer(1, title=AOC))
    put(conn, offer(1, title="Monitor Gamer Asus Tuf Vg27aqme5f 27 QHD"))
    assert _codes(conn, 1) == ["VG27AQME5F"]


def test_coupons_and_titles_without_a_code_store_none(conn: sqlite3.Connection) -> None:
    put(
        conn,
        offer(1, title="Cupom Kabum U34G4C", kind=OfferKind.coupon),
        offer(2, title="Camiseta Dry Fit Preta"),
    )
    assert _codes(conn, 1) == [] and _codes(conn, 2) == []


# --- peers: the same product in other stores ---------------------------------------------------


def _peers(conn: sqlite3.Connection, message_id: int) -> list[tuple[str, int]]:
    found = SqliteOfferQueries(conn).peers([(1, message_id)], NOW)
    return [(p.store, p.price_cents) for p in found.get((1, message_id), ())]


def test_peers_are_the_latest_price_per_other_store_cheapest_first(
    conn: sqlite3.Connection,
) -> None:
    put(
        conn,
        offer(1, title=AOC, store="amazon", price=150000),
        offer(2, title=AOC, store="kabum", price=144400),
        offer(3, title=AOC, store="kabum", price=139900, at=T0 + timedelta(days=2)),  # newer
        offer(4, title=AOC + " Preto", store="magalu", price=141900),
    )
    assert _peers(conn, 1) == [("kabum", 139900), ("magalu", 141900)]


def test_peers_never_include_the_offers_own_store(conn: sqlite3.Connection) -> None:
    put(
        conn,
        offer(1, title=AOC, store="amazon", price=150000),
        offer(2, title=AOC, store="amazon", price=140000),
    )
    assert _peers(conn, 1) == []


def test_a_veto_keeps_a_different_variant_out(conn: sqlite3.Connection) -> None:
    put(
        conn,
        offer(1, title="Samsung Galaxy A57 128Gb 5G", store="amazon", price=180000),
        offer(2, title="Samsung Galaxy A57 256Gb 5G", store="kabum", price=200000),
        offer(
            3, title="Combo Samsung Galaxy A57 128Gb + Galaxy Buds", store="magalu", price=190000
        ),
        offer(4, title="Samsung Galaxy A57 128Gb Azul 5G", store="mercadolivre", price=158300),
    )
    assert _peers(conn, 1) == [("mercadolivre", 158300)]


def test_a_code_carried_by_too_many_offers_is_not_a_model(conn: sqlite3.Connection) -> None:
    # RTX5060 is a chip, not a product: 25 different offers carry it
    put(
        conn,
        *[
            offer(
                i,
                title=f"Placa de Video RTX 5060 Modelo{i} Extra{i}",
                store=f"loja{i}",
                price=250000,
            )
            for i in range(1, 26)
        ],
    )
    assert _peers(conn, 1) == []


def test_peers_ignore_old_deleted_unpriced_and_non_product_offers(conn: sqlite3.Connection) -> None:
    put(
        conn,
        offer(1, title=AOC, store="amazon", price=150000, at=NOW - timedelta(hours=1)),
        offer(2, title=AOC, store="kabum", price=140000, at=NOW - timedelta(days=30)),  # too old
        offer(3, title=AOC, store="magalu", price=141000, deleted=True),
        offer(4, title=AOC, store="shopee", price=None),
        offer(5, title=AOC, store="pichau", price=142000, kind=OfferKind.coupon),
    )
    assert _peers(conn, 1) == []


def test_peers_for_a_batch_of_cards(conn: sqlite3.Connection) -> None:
    put(
        conn,
        offer(1, title=AOC, store="amazon", price=150000),
        offer(2, title=AOC, store="kabum", price=144400),
        offer(3, title="Camiseta Dry Fit Preta", store="amazon", price=5000),
    )
    found = SqliteOfferQueries(conn).peers([(1, 1), (1, 2), (1, 3), (1, 999)], NOW)
    assert [p.store for p in found[(1, 1)]] == ["kabum"]
    assert [p.store for p in found[(1, 2)]] == ["amazon"]
    assert (1, 3) not in found and (1, 999) not in found


# --- same_product: the history behind the product page ----------------------------------------


def test_same_product_keeps_every_priced_offer_of_every_store_oldest_first(
    conn: sqlite3.Connection,
) -> None:
    put(
        conn,
        offer(1, title=AOC, store="amazon", price=150000, at=T0),
        offer(2, title=AOC, store="kabum", price=144400, at=T0 + timedelta(days=1)),
        offer(3, title=AOC, store="amazon", price=139900, at=T0 + timedelta(days=2)),  # same store
        offer(4, title=AOC, store="magalu", price=141900, at=NOW - timedelta(days=60)),  # old: kept
    )
    history = SqliteOfferQueries(conn).same_product(1, 3)
    assert history is not None
    assert [(o.store, o.price_cents) for o in history.offers] == [
        ("magalu", 141900),  # the oldest, 60 days back: history is kept, not windowed
        ("amazon", 150000),
        ("kabum", 144400),
        ("amazon", 139900),
    ]


def test_same_product_is_none_for_an_unknown_or_non_product_offer(conn: sqlite3.Connection) -> None:
    put(conn, offer(1, title="Cupom U34G4C", kind=OfferKind.coupon))
    q = SqliteOfferQueries(conn)
    assert q.same_product(1, 1) is None
    assert q.same_product(1, 999) is None


def test_same_product_with_no_other_store_still_returns_the_offer_itself(
    conn: sqlite3.Connection,
) -> None:
    put(conn, offer(1, title=AOC, store="amazon", price=150000))
    history = SqliteOfferQueries(conn).same_product(1, 1)
    assert history is not None and [o.store for o in history.offers] == ["amazon"]
    assert (history.title, history.store) == (AOC, "amazon")
