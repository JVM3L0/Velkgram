"""The same product across stores: the 'also in' line on cards and the product page."""

import sqlite3
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings
from tests.fakes.clock import FakeClock
from tests.offers.adapters._queries_helpers import T0, offer, put
from velkgram.offers.domain.models import OfferKind
from velkgram.shared.db import connect

NOW = T0 + timedelta(days=30)
AOC = 'Monitor Gamer Curvo Aoc Gaming U34g4c 34" Wqhd 180Hz'


def _client(tmp_path: Path) -> TestClient:
    client = make_client(tmp_path, clock=FakeClock(NOW))
    conn = connect(make_settings(tmp_path).db_path)
    try:
        conn.execute(
            "INSERT INTO channels (id, ref, telegram_id, name, status, enabled, "
            "silent_after_hours, created_at) VALUES (1, '@c1', 1, 'Promos BR', 'active', 1, 12, ?)",
            (T0.isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()
    return client


def _conn(tmp_path: Path) -> sqlite3.Connection:
    return connect(make_settings(tmp_path).db_path)


def _seed(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    put(
        conn,
        offer(1, title=AOC, store="amazon", price=150000, at=NOW - timedelta(hours=3)),
        offer(2, title=AOC, store="kabum", price=144400, at=NOW - timedelta(hours=2)),
        offer(3, title=AOC, store="magalu", price=141900, at=NOW - timedelta(days=5)),
        offer(4, title=AOC, store="kabum", price=139900, at=NOW - timedelta(days=20)),  # history
        offer(
            5,
            title="Camiseta Dry Fit Preta",
            store="amazon",
            price=5000,
            at=NOW - timedelta(hours=1),
        ),
    )
    conn.close()


# --- the line on a card ------------------------------------------------------------------------


def test_a_card_lists_the_same_product_in_other_stores_and_links_to_the_comparison(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    _seed(tmp_path)
    page = client.get("/").text
    assert "Também em" in page
    assert "R$ 1.419,00" in page or "R$ 1.444,00" in page
    assert 'href="/produto/1/1"' in page  # the Amazon card links to its comparison


def test_a_card_with_no_other_store_shows_no_line(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conn = _conn(tmp_path)
    put(conn, offer(1, title="Camiseta Dry Fit Preta", store="amazon", price=5000, at=NOW))
    conn.close()
    assert "Também em" not in client.get("/").text


def test_a_cheaper_peer_is_marked(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path)
    page = client.get("/").text
    assert "peer-cheaper" in page  # kabum / magalu are cheaper than amazon's R$ 1.500


# --- the product page --------------------------------------------------------------------------


def test_the_page_shows_each_store_with_current_and_lowest_price(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path)
    page = client.get("/produto/1/1")
    assert page.status_code == 200
    text = page.text
    assert "U34g4c" in text  # the product title
    for store in ("Amazon", "KaBuM", "Magalu"):  # display names, not the slugs
        assert store in text
    assert "R$ 1.399,00" in text  # kabum's old low is the lowest price ever seen
    assert "Menor preço registrado" in text


def test_the_page_keeps_the_history_beyond_the_peer_window(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path)
    text = client.get("/produto/1/1").text
    # kabum has two offers (R$ 1.444 now, R$ 1.399 twenty days ago): both counted
    assert "2 ofertas" in text


def test_the_page_says_so_when_no_other_store_has_the_product(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conn = _conn(tmp_path)
    put(conn, offer(1, title="Camiseta Dry Fit Preta", store="amazon", price=5000, at=NOW))
    conn.close()
    page = client.get("/produto/1/1")
    assert page.status_code == 200
    assert "outras lojas" in page.text


def test_unknown_offers_and_coupons_are_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conn = _conn(tmp_path)
    put(conn, offer(1, title="Cupom Kabum U34G4C", kind=OfferKind.coupon))
    conn.close()
    assert client.get("/produto/1/999").status_code == 404
    assert client.get("/produto/1/1").status_code == 404
    assert (
        client.get("/produto/abc/1").status_code == 422
        or client.get("/produto/abc/1").status_code == 404
    )


def test_the_page_needs_a_login(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False)
    response = client.get("/produto/1/1")
    assert (response.status_code, response.headers["location"]) == (303, "/login")


def test_the_store_links_are_safe(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conn = _conn(tmp_path)
    put(
        conn,
        offer(1, title=AOC, store="amazon", price=150000, at=NOW, link="https://x.test/a"),
        offer(2, title=AOC, store="kabum", price=144400, at=NOW, link="javascript:alert(1)"),
    )
    conn.close()
    text = client.get("/produto/1/1").text
    assert "javascript:" not in text
    assert 'href="https://x.test/a"' in text and 'rel="noopener noreferrer"' in text
