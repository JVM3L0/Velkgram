"""Live updates: the poller on each page and the count endpoints behind the "new items" pill."""

import html
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

from tests.offers.adapters._queries_helpers import offer, put
from tests.offers.web.test_coupons_ui import NOW, _coupon
from tests.offers.web.test_coupons_ui import _client as coupons_client
from tests.offers.web.test_feed_page import _client as feed_client
from velkgram.shared.db import connect

POLLER = re.compile(r'hx-get="(/(?:cupons/)?novidades\?[^"]+)" hx-trigger="every 30s')


def _since(page: str) -> str:
    match = POLLER.search(page)
    assert match is not None
    return html.unescape(match.group(1))


def _add(tmp_path: Path, *offers: object) -> None:
    conn = connect(tmp_path / "web.db")
    try:
        put(conn, *offers)  # type: ignore[arg-type]
    finally:
        conn.close()


def _at(minutes: int) -> object:
    return NOW - timedelta(minutes=minutes)


def test_feed_has_exactly_one_poller(tmp_path: Path) -> None:
    client = feed_client(
        tmp_path, *[offer(i, title=f"P{i}", at=NOW - timedelta(minutes=i)) for i in range(1, 40)]
    )
    page = client.get("/").text
    assert page.count("every 30s") == 1
    assert "document.visibilityState === 'visible'" in html.unescape(page)
    assert 'aria-live="polite"' in page
    nxt = re.search(r'hx-get="(/\?[^"]+cursor[^"]+)"', page)
    assert nxt is not None
    fragment = client.get(html.unescape(nxt.group(1)), headers={"HX-Request": "true"}).text
    assert "every 30s" not in fragment and "data-live" not in fragment


def test_coupons_page_has_exactly_one_poller(tmp_path: Path) -> None:
    client = coupons_client(tmp_path, _coupon(2))
    assert client.get("/cupons").text.count("every 30s") == 1


def test_feed_news_counts_rows_after_the_first_cursor(tmp_path: Path) -> None:
    client = feed_client(tmp_path, offer(1, title="Antigo", at=NOW - timedelta(hours=1)))
    url = _since(client.get("/").text)
    assert client.get(url).status_code == 204
    _add(tmp_path, offer(2, title="Nova A", at=NOW), offer(3, title="Nova B", at=NOW))
    res = client.get(url)
    assert res.status_code == 200
    assert "2 novas ofertas" in res.text
    assert "arrow_upward" in res.text and 'data-live-count="2"' in res.text
    _add(tmp_path, offer(4, title="Mais", at=NOW + timedelta(minutes=1)))
    assert "3 novas ofertas" in client.get(url).text


def test_feed_news_singular(tmp_path: Path) -> None:
    client = feed_client(tmp_path, offer(1, at=NOW - timedelta(hours=1)))
    url = _since(client.get("/").text)
    _add(tmp_path, offer(2, at=NOW))
    assert "1 nova oferta" in client.get(url).text


def test_feed_news_pill_reloads_the_first_page_with_the_filters(tmp_path: Path) -> None:
    client = feed_client(tmp_path, offer(1, store="kabum", at=NOW - timedelta(hours=1)))
    url = _since(client.get("/", params={"store": "kabum", "priced": "1"}).text)
    _add(tmp_path, offer(2, store="kabum", at=NOW))
    pill = html.unescape(client.get(url).text)
    assert 'hx-get="/?store=kabum&priced=1&view=cards"' in pill
    assert 'hx-select="#results"' in pill and 'hx-target="#results"' in pill


def test_feed_news_respects_the_filters(tmp_path: Path) -> None:
    client = feed_client(tmp_path, offer(1, store="kabum", at=NOW - timedelta(hours=1)))
    url = _since(client.get("/", params={"store": "kabum"}).text)
    _add(tmp_path, offer(2, store="amazon", at=NOW), offer(3, store="kabum", price=None, at=NOW))
    assert "1 nova oferta" in client.get(url).text
    assert client.get(url + "&priced=1").status_code == 204
    only_kabum = client.get(url.replace("store=kabum", "store=kabum&q=zzzz"))
    assert only_kabum.status_code == 204


def test_feed_news_empty_list_counts_from_render_time(tmp_path: Path) -> None:
    client = feed_client(tmp_path)
    url = _since(client.get("/").text)
    assert client.get(url).status_code == 204
    _add(tmp_path, offer(1, at=NOW - timedelta(minutes=5)))
    assert client.get(url).status_code == 204  # posted before the page was rendered
    _add(tmp_path, offer(2, at=NOW + timedelta(seconds=30)))
    assert "1 nova oferta" in client.get(url).text


def test_feed_news_tie_on_posted_at_uses_the_full_cursor(tmp_path: Path) -> None:
    client = feed_client(tmp_path, offer(5, channel_id=1, at=NOW))
    url = _since(client.get("/").text)
    _add(tmp_path, offer(4, channel_id=1, at=NOW), offer(6, channel_id=1, at=NOW))
    assert "1 nova oferta" in client.get(url).text


def test_feed_news_ignores_coupons_and_reposts(tmp_path: Path) -> None:
    client = feed_client(tmp_path, offer(1, at=NOW - timedelta(hours=1)))
    url = _since(client.get("/").text)
    _add(tmp_path, _coupon(2, at=NOW))
    assert client.get(url).status_code == 204


def test_feed_news_malformed_since_is_204(tmp_path: Path) -> None:
    client = feed_client(tmp_path, offer(1))
    for bad in (
        "",
        "x",
        "a|b|c",
        "2026-01-01T00:00:00|1|1",
        "2026-01-01T00:00:00+00:00|1",
        quote("|||"),
    ):
        assert client.get("/novidades", params={"since": bad}).status_code == 204
    assert client.get("/novidades").status_code == 204


def test_news_requires_login(tmp_path: Path) -> None:
    client = feed_client(tmp_path, login=False)
    assert client.get("/novidades", follow_redirects=False).status_code in (303, 401)
    assert client.get("/cupons/novidades", follow_redirects=False).status_code in (303, 401)


def test_coupons_news_counts_with_the_store_filter(tmp_path: Path) -> None:
    client = coupons_client(tmp_path, _coupon(1, at=NOW - timedelta(hours=2)))
    url = _since(client.get("/cupons").text)
    assert client.get(url).status_code == 204
    _add(tmp_path, _coupon(2, at=NOW), _coupon(3, store="amazon", at=NOW))
    assert "2 novos cupons" in client.get(url).text
    assert "1 novo cupom" in client.get(url + "&loja=amazon").text
    assert client.get(url + "&loja=kabum").status_code == 204


def test_coupons_news_respects_search_and_active_window(tmp_path: Path) -> None:
    client = coupons_client(tmp_path, _coupon(1, at=NOW - timedelta(hours=2)))
    url = _since(client.get("/cupons", params={"q": "zzz"}).text)
    _add(tmp_path, _coupon(2, at=NOW))
    assert client.get(url).status_code == 204
    all_url = _since(client.get("/cupons", params={"ativos": "0"}).text)
    _add(tmp_path, _coupon(3, at=NOW + timedelta(minutes=1)))
    pill = html.unescape(client.get(all_url).text)
    assert "1 novo cupom" in pill and 'hx-get="/cupons?ativos=0"' in pill


def test_coupons_news_malformed_since_is_204(tmp_path: Path) -> None:
    client = coupons_client(tmp_path, _coupon(1))
    assert client.get("/cupons/novidades", params={"since": "lixo"}).status_code == 204
    assert client.get("/cupons/novidades").status_code == 204
