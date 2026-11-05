import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tests.offers.web.test_coupons_ui import NOW, _client, _coupon, _product
from velkgram.offers.adapters.sqlite.queries import SqliteOfferQueries
from velkgram.offers.domain.models import Offer


def _page(tmp_path: Path, *offers: Offer, **params: str) -> str:
    return _client(tmp_path, *offers).get("/cupons", params=params).text


def _cards(page: str) -> list[str]:
    return re.findall(r'<article id="cupom-\d+-\d+".*?</article>', page, re.DOTALL)


def test_tabs_are_links_with_the_current_one_marked_on_both_pages(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path, current in (("/", "Ofertas"), ("/cupons", "Cupons")):
        page = client.get(path).text
        nav = re.search(
            r'<nav class="tabs feed-tabs" aria-label="Seções do feed">(.*?)</nav>', page, re.DOTALL
        )
        assert nav is not None and 'role="tab' not in page
        tabs = re.findall(r"<a [^>]*>.*?</a>", nav.group(1), re.DOTALL)
        assert len(tabs) == 2
        assert [("/" if "Ofertas" in t else "/cupons") in t for t in tabs] == [True, True]
        marked = [t for t in tabs if 'aria-current="page"' in t]
        assert len(marked) == 1 and current in marked[0]
        assert 'href="/cupons"' in page and 'href="/"' in page


def test_nav_feed_item_stays_current_on_cupons(tmp_path: Path) -> None:
    page = _client(tmp_path).get("/cupons").text
    nav = re.findall(r'<a href="/"[^>]*class="active"', page)
    assert len(nav) == 2  # bottom bar and side rail


def test_lists_full_coupon_cards_newest_first_without_products(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        _coupon(1, at=NOW - timedelta(hours=5), title="Cupom Antigo"),
        _coupon(2, at=NOW - timedelta(hours=1)),
        _product(3),
    )
    ids = re.findall(r'<article id="(cupom-\d+-\d+)"', page)
    assert ids == ["cupom-1-2", "cupom-1-1"]
    assert "Placa de Video" not in page
    assert "Ver post completo" in page


def test_only_active_is_on_by_default_and_ativos_0_turns_it_off(tmp_path: Path) -> None:
    client = _client(
        tmp_path, _coupon(1, at=NOW - timedelta(hours=30)), _coupon(2, at=NOW - timedelta(hours=2))
    )
    on = client.get("/cupons").text
    assert len(_cards(on)) == 1
    off = client.get("/cupons", params={"ativos": "0"}).text
    assert len(_cards(off)) == 2
    both = client.get("/cupons?ativos=0&ativos=1").text
    assert len(_cards(both)) == 1  # the checked switch is sent after its hidden 0
    switch = re.search(r'<input[^>]*type="checkbox"[^>]*name="ativos"[^>]*>', on)
    assert switch is not None and "checked" in switch.group(0)
    switch_off = re.search(r'<input[^>]*type="checkbox"[^>]*name="ativos"[^>]*>', off)
    assert switch_off is not None and "checked" not in switch_off.group(0)
    assert "Só ativos" in on


def test_store_select_lists_stores_with_coupons_and_filters(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        _coupon(1, store="shopee"),
        _coupon(2, store="amazon"),
        _product(3, store="magalu"),
    )
    page = client.get("/cupons", params={"loja": "amazon"}).text
    assert len(_cards(page)) == 1 and "cupom-1-2" in page
    boxes = re.findall(r'<input type="checkbox" name="loja" value="([^"]*)"( checked)?', page)
    assert [o[0] for o in boxes] == ["amazon", "shopee"]
    assert [o[0] for o in boxes if o[1]] == ["amazon"]


def test_search_matches_code_title_or_store_including_display_name(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        _coupon(1, coupon=("ZAFA10",), title="Cupom Shopee"),
        _coupon(2, coupon=("KORUJAO",), store="mercadolivre", title="Cupom ML"),
    )
    for q, expected in (("zafa", "cupom-1-1"), ("ml", "cupom-1-2"), ("mercado livre", "cupom-1-2")):
        page = client.get("/cupons", params={"q": q}).text
        assert [expected] == re.findall(r'<article id="(cupom-\d+-\d+)"', page), q


def test_pagination_uses_cursor_and_revealed_trigger(tmp_path: Path) -> None:
    offers = [_coupon(i, at=NOW - timedelta(minutes=i)) for i in range(1, 35)]
    client = _client(tmp_path, *offers)
    page = client.get("/cupons", params={"loja": "shopee"}).text
    assert len(_cards(page)) == 30
    nxt = re.search(r'hx-get="([^"]+)" hx-trigger="revealed, click"', page)
    assert nxt is not None
    url = nxt.group(1).replace("&amp;", "&")
    assert "loja=shopee" in url and "cursor=" in url
    fragment = client.get(url, headers={"HX-Request": "true"}).text
    assert "<html" not in fragment
    assert len(_cards(fragment)) == 4 and "revealed" not in fragment


def test_empty_state_offers_a_way_to_clear_filters(tmp_path: Path) -> None:
    page = _page(tmp_path, _coupon(1), q="nada")
    assert "Nenhum cupom por aqui." in page
    assert 'href="/cupons"' in page[page.index("Nenhum cupom") :]
    assert "<article" not in page


def test_old_tipo_filter_redirects_to_cupons_keeping_store_and_query(tmp_path: Path) -> None:
    client = _client(tmp_path)
    r = client.get("/", params={"tipo": "cupons", "store": "amazon", "q": "x y"})
    assert r.status_code == 303
    assert r.headers["location"] == "/cupons?loja=amazon&q=x+y"
    assert client.get("/", params={"tipo": "cupons"}).headers["location"] == "/cupons"


def test_feed_has_no_coupon_chip_or_strip(tmp_path: Path) -> None:
    page = _client(tmp_path, _product(1), _coupon(2)).get("/").text
    assert 'name="tipo"' not in page and "Ver todos" not in page


def test_product_card_links_to_the_stores_recent_coupons(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        _product(1, store="shopee"),
        _product(2, store="amazon"),
        _coupon(3, store="shopee"),
        _coupon(4, store="shopee", at=NOW - timedelta(hours=3)),
        _coupon(5, store="shopee", at=NOW - timedelta(hours=30)),
        _coupon(6, store="amazon", at=NOW - timedelta(hours=2)),
    )
    page = client.get("/").text
    assert '<a class="chip small tonal-chip store-coupons" href="/cupons?loja=shopee">' in page
    assert "2 cupons da loja" in page
    assert "1 cupom da loja" in page and "1 cupons" not in page
    assert page.count("cupons da loja") + page.count("cupom da loja") == 2


def test_product_card_without_store_coupons_has_no_chip(tmp_path: Path) -> None:
    client = _client(
        tmp_path, _product(1, store="shopee"), _coupon(2, at=NOW - timedelta(hours=40))
    )
    assert "da loja" not in client.get("/").text


def test_store_coupon_counts_are_one_query_per_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    original = SqliteOfferQueries.coupon_counts

    def counting(self: SqliteOfferQueries, now: datetime, hours: int = 24) -> dict[str, int]:
        calls.append(1)
        return original(self, now, hours)

    client = _client(tmp_path, *(_product(i) for i in range(1, 6)), _coupon(9))
    monkeypatch.setattr(SqliteOfferQueries, "coupon_counts", counting)
    client.get("/")
    assert len(calls) == 1


def test_product_page_match_cards_carry_the_store_coupon_chip(tmp_path: Path) -> None:
    from tests.apps.web_support import make_settings
    from tests.offers.adapters._queries_helpers import match, put
    from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository
    from velkgram.offers.domain.models import MatchSource
    from velkgram.shared.db import connect

    client = _client(tmp_path, _coupon(2, store="amazon"))
    client.post(
        "/wishes/new",
        data={"name": "SSD", "required_terms": "ssd", "excluded_terms": "", "max_price": "500,00"},
    )
    conn = connect(make_settings(tmp_path).db_path)
    try:
        product = _product(1, store="amazon")
        put(conn, product)
        SqliteOfferRepository(conn).add_match(match(1, product, MatchSource.live))
    finally:
        conn.close()
    page = client.get("/wishes/1").text
    assert 'href="/cupons?loja=amazon"' in page and "1 cupom da loja" in page


def test_redirect_keeps_every_store_and_the_active_switch(tmp_path: Path) -> None:
    client = _client(tmp_path)
    r = client.get(
        "/", params=[("tipo", "cupons"), ("store", "amazon"), ("store", "shopee"), ("ativos", "0")]
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/cupons?loja=amazon&loja=shopee&ativos=0"


def test_several_stores_filter_and_unknown_store_is_not_all_stores(tmp_path: Path) -> None:
    offers = (_coupon(1, store="shopee"), _coupon(2, store="amazon"), _coupon(3, store="kabum"))
    client = _client(tmp_path, *offers)
    page = client.get("/cupons", params=[("loja", "shopee"), ("loja", "kabum")]).text
    assert [c for c in ("cupom-1-1", "cupom-1-2", "cupom-1-3") if f'id="{c}"' in page] == [
        "cupom-1-1",
        "cupom-1-3",
    ]
    page = client.get("/cupons", params={"loja": "naoexiste"}).text
    assert _cards(page) == [] and "Nenhum cupom por aqui." in page
    assert 'name="loja" value="naoexiste" checked' in page
    page = client.get("/cupons", params=[("loja", "shopee"), ("loja", "kabum")]).text
    checked = re.findall(r'name="loja" value="([^"]*)" checked', page)
    assert checked == ["shopee", "kabum"] or sorted(checked) == ["kabum", "shopee"]
