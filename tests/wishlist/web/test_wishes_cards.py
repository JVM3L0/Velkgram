from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings
from tests.offers.adapters._queries_helpers import match, offer, put
from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository
from velkgram.offers.domain.models import MatchSource
from velkgram.shared.db import connect

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _client(tmp_path: Path) -> TestClient:
    client = make_client(tmp_path)
    response = client.post(
        "/wishes/new",
        data={
            "name": "SSD 1TB",
            "required_terms": "ssd",
            "excluded_terms": "",
            "max_price": "300,00",
        },
    )
    assert response.status_code == 303
    return client


def _seed(tmp_path: Path, prices: list[int]) -> None:
    conn = connect(make_settings(tmp_path).db_path)
    try:
        repo = SqliteOfferRepository(conn)
        for mid, price in enumerate(prices, start=1):
            o = offer(mid, at=NOW - timedelta(days=len(prices) - mid), price=price)
            put(conn, o)
            repo.add_match(match(1, o, MatchSource.live))
    finally:
        conn.close()


def _count(tmp_path: Path, table: str) -> int:
    conn = connect(make_settings(tmp_path).db_path)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def test_wish_cards_show_last_price_and_sparkline(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [25000, 22000, 20000])
    page = client.get("/wishes").text
    assert "<h1>Desejos</h1>" in page
    assert "R$ 200,00" in page
    assert "<svg" in page
    assert "3 ofertas" in page
    assert 'href="/wishes/new"' in page
    assert "Novo desejo" in page


def test_wish_card_without_matches_shows_placeholder(tmp_path: Path) -> None:
    page = _client(tmp_path).get("/wishes").text
    assert "sem ofertas" in page
    assert "<svg" not in page


def test_wish_card_links_to_product_page(tmp_path: Path) -> None:
    page = _client(tmp_path).get("/wishes").text
    assert 'href="/wishes/1"' in page


def test_wish_toggle_shows_state_and_action(tmp_path: Path) -> None:
    client = _client(tmp_path)
    page = client.get("/wishes").text
    assert "ativo" in page
    assert "Pausar" in page
    fragment = client.post("/wishes/1/toggle").text
    assert "pausado" in fragment
    assert "Retomar" in fragment
    assert "Pausar" not in fragment


def test_toggle_fragment_keeps_stats(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [25000, 20000])
    fragment = client.post("/wishes/1/toggle").text
    assert "<html" not in fragment
    assert "R$ 200,00" in fragment
    assert "<svg" in fragment
    assert "2 ofertas" in fragment


def test_delete_calls_on_deleted(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [25000, 20000])
    assert _count(tmp_path, "offer_matches") == 2
    assert client.post("/wishes/1/delete").status_code == 303
    assert _count(tmp_path, "wishes") == 0
    assert _count(tmp_path, "offer_matches") == 0


def test_edit_and_toggle_reach_wishlist_router_with_offers_mounted(tmp_path: Path) -> None:
    client = _client(tmp_path)
    edit = client.get("/wishes/1/edit")
    assert edit.status_code == 200
    assert "Termos obrigatórios" in edit.text
    toggle = client.post("/wishes/1/toggle")
    assert toggle.status_code == 200
    assert 'id="wish-1"' in toggle.text
