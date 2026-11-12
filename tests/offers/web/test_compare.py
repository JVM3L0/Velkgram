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
    assert "Menor preço (sempre)" in text


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


# --- the same layout as a wish: insight, period switch and the lowest-price chart ------------


def test_the_page_has_the_wish_layout_without_an_alert_line(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path)
    text = client.get("/produto/1/1").text
    assert "Preço atual" in text  # the insight block
    assert "R$ 1.419,00" in text  # the cheapest current price across stores (magalu, 5 days ago)
    for label in ("30 dias", "90 dias", "Tudo"):
        assert label in text
    assert 'href="/produto/1/1?range=30"' in text
    assert "chart-step" in text and "menor preço do dia" in text
    assert "seu alerta" not in text.lower()


def test_the_period_switch_changes_which_days_are_charted(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path)
    conn = _conn(tmp_path)
    put(conn, offer(6, title=AOC, store="kabum", price=120000, at=NOW - timedelta(days=60)))
    conn.close()
    thirty = client.get("/produto/1/1?range=30").text
    everything = client.get("/produto/1/1?range=all").text
    # the chart's table lists one row per charted day; the old R$ 1.200 offer is outside 30 days
    assert "<td>R$ 1.200,00</td>" not in thirty
    assert "<td>R$ 1.200,00</td>" in everything
    assert "Menor preço (sempre)" in thirty and "R$ 1.200,00" in thirty  # the all-time low stays
    assert 'aria-current="true">30 dias' in thirty
    assert 'aria-current="true">Tudo' in everything


def test_the_chart_block_can_be_fetched_on_its_own_for_the_period_switch(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path)
    block = client.get("/produto/1/1/chart?range=30")
    assert block.status_code == 200
    assert 'id="chart-block"' in block.text and "<html" not in block.text
    assert 'hx-get="/produto/1/1/chart?range=30"' in block.text
    assert "seu alerta" not in block.text.lower()


def test_the_chart_partial_is_404_for_an_unknown_offer(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/produto/1/999/chart").status_code == 404


def test_the_offer_list_shows_every_offer_newest_first(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path)
    text = client.get("/produto/1/1").text
    section = text.split('id="offers-title"')[1]
    assert section.index("R$ 1.500,00") < section.index("R$ 1.399,00")  # 3 h ago before 20 d ago


def test_the_chart_ends_at_the_current_lowest_price_like_the_summary(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path)
    text = client.get("/produto/1/1").text
    # the newest day's cheapest offer is kabum's R$ 1.444, but magalu's R$ 1.419 (5 days ago) is
    # still the lowest current price: the summary says so and the chart's last label agrees
    assert "R$ 1.419,00" in text.split('id="chart-block"')[1].split("</section>")[0]
    assert "Atual R$ 1.419,00" in text


def test_the_page_shows_the_product_title_as_its_heading(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path)
    text = client.get("/produto/1/1").text
    assert "<h1>" in text and "U34g4c" in text.split("<h1>")[1].split("</h1>")[0]
    assert "page-title" not in text  # nothing replaces the product name in the app bar
