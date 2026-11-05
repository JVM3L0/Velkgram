import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from tests.apps.web_support import make_client
from tests.fakes.clock import FakeClock
from tests.offers.adapters._queries_helpers import offer, put
from velkgram.offers.domain.models import Offer
from velkgram.shared.db import connect

NOW = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)


def _client(tmp_path: Path, *offers: Offer, login: bool = True) -> TestClient:
    client = make_client(tmp_path, login=login, clock=FakeClock(NOW))
    conn = connect(tmp_path / "web.db")
    try:
        put(conn, *offers)
    finally:
        conn.close()
    return client


def _many(n: int) -> list[Offer]:
    return [offer(i, title=f"Produto {i}") for i in range(1, n + 1)]


def test_feed_lists_cards_newest_first(tmp_path: Path) -> None:
    client = _client(tmp_path, offer(1, title="Antigo"), offer(2, title="Recente"))
    html = client.get("/").text
    assert html.index("Recente") < html.index("Antigo")
    assert "R$ 299,90" in html
    assert "Amazon" in html
    assert "Acompanhar" in html


def test_feed_filters_from_query_string(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        offer(1, title="Teclado", price=10000, store="kabum", text="teclado"),
        offer(2, title="Mouse", price=20000, store="amazon", text="mouse"),
        offer(3, title="Cabo", price=None, store="amazon", text="cabo"),
    )
    html = client.get("/", params={"store": "kabum"}).text
    assert "Teclado" in html and "Mouse" not in html
    html = client.get("/", params={"priced": "1"}).text
    assert "Cabo" not in html and "Mouse" in html
    html = client.get("/", params={"q": "mouse"}).text
    assert "Mouse" in html and "Teclado" not in html


def test_feed_htmx_next_page_returns_fragment_only(tmp_path: Path) -> None:
    client = _client(tmp_path, *_many(35))
    first = client.get("/").text
    match = re.search(r'hx-get="(/\?[^"]+)"', first)
    assert match is not None
    url = match.group(1).replace("&amp;", "&")
    page = client.get(url, headers={"HX-Request": "true"}).text
    assert "<html" not in page
    assert "Produto 5" in page
    assert "hx-trigger" not in page  # last page: no further trigger


def test_feed_empty_state(tmp_path: Path) -> None:
    assert "Nenhuma oferta encontrada" in _client(tmp_path).get("/").text


def test_feed_search_notice_shows_retention_days(tmp_path: Path) -> None:
    client = _client(tmp_path, offer(1))
    assert "A busca cobre os últimos 90 dias." in client.get("/", params={"q": "ssd"}).text
    assert "A busca cobre" not in client.get("/").text


def test_feed_never_renders_non_http_links(tmp_path: Path) -> None:
    import dataclasses

    bad = dataclasses.replace(offer(1), main_link="javascript:alert(1)")
    worse = dataclasses.replace(offer(2), main_link="tg://x")
    html = _client(tmp_path, bad, worse).get("/").text
    assert "javascript:" not in html
    assert "tg://" not in html


def test_feed_escapes_title_html(tmp_path: Path) -> None:
    html = _client(tmp_path, offer(1, title="<script>alert(1)</script>")).get("/").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_root_requires_login(tmp_path: Path) -> None:
    response = _client(tmp_path, login=False).get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_next_page_link_preserves_filters(tmp_path: Path) -> None:
    client = _client(tmp_path, *_many(35))
    html = client.get("/", params={"store": "amazon", "priced": "1", "q": "produto"}).text
    match = re.search(r'hx-get="(/\?[^"]+)"', html)
    assert match is not None
    url = match.group(1).replace("&amp;", "&")
    assert "store=amazon" in url and "priced=1" in url and "q=produto" in url
    assert "cursor=" in url
    assert 'hx-trigger="revealed"' in html and 'hx-swap="afterend"' in html


def test_malformed_cursor_gives_first_page(tmp_path: Path) -> None:
    client = _client(tmp_path, *_many(3))
    huge = "99999999999999999999"
    for cursor in (
        "garbage",
        "2026-01-01|x|y",
        "|1|2",
        "a|b",
        f"2026-11-05T00:00:00+00:00|{huge}|1",
    ):
        response = client.get("/", params={"cursor": cursor})
        assert response.status_code == 200
        assert "Produto 3" in response.text


def test_invalid_channel_and_price_params_are_ignored(tmp_path: Path) -> None:
    client = _client(tmp_path, *_many(2))
    response = client.get("/", params={"channel": "abc", "min": "x,y", "max": "--"})
    assert response.status_code == 200
    assert "Produto 2" in response.text and "Produto 1" in response.text


def test_price_filter_excludes_unknown_prices(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        offer(1, title="Com preço", price=50000),
        offer(2, title="Sem preço", price=None),
    )
    html = client.get("/", params={"min": "100,00"}).text
    assert "Com preço" in html and "Sem preço" not in html
    html = client.get("/", params={"max": "9999"}).text
    assert "Sem preço" not in html
    assert "Com preço" in client.get("/").text and "Sem preço" in client.get("/").text


def test_old_root_redirect_is_gone(tmp_path: Path) -> None:
    assert _client(tmp_path).get("/").status_code == 200


def test_feed_view_toggle_says_grade_not_cards(tmp_path: Path) -> None:
    page = make_client(tmp_path).get("/").text
    assert "Grade" in page and "Cards</span>" not in page


def test_feed_card_has_one_filled_button_and_an_icon_only_follow_heart(tmp_path: Path) -> None:
    html = _client(tmp_path, offer(1)).get("/").text
    assert re.search(r'<a class="button small" href="https://x\.test/p"', html)
    follow = re.search(r'<a class="button circle tonal"[^>]*href="/wishes/new\?[^>]*>', html)
    assert follow is not None
    assert 'aria-label="Acompanhar"' in follow.group(0)
    assert 'title="Acompanhar"' in follow.group(0)
    assert "<span>Acompanhar</span>" not in html


def test_feed_card_without_comparable_price_uses_the_quiet_layout(tmp_path: Path) -> None:
    html = (
        _client(
            tmp_path,
            offer(1, title="Normal"),
            offer(2, title="Cupom Kabum 10%", comparable=False),
            offer(3, title="Sem preço", price=None),
        )
        .get("/")
        .text
    )
    cards = re.findall(r'<article class="([^"]*)"', html)
    assert sorted("offer-quiet" in c for c in cards) == [False, True, True]
