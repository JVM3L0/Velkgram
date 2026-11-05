import re
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings
from tests.fakes.clock import FakeClock
from tests.offers.adapters._queries_helpers import match, offer, put
from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository
from velkgram.offers.domain.models import CouponTier, MatchSource, Offer, OfferKind
from velkgram.shared.db import connect

NOW = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
PALIT = "Placa de Video Palit RTX 5070\n\nR$ 4679\n-CUPOM: ZAFADINHO10\n\nhttps://cutt.ly/XyIWx4MZ"
SHOPEE = (
    "Cupom Shopee\n\nR$ 10 OFF em R$ 40: QIP98Q1ZXO\n\n-Resgate aqui:\n"
    "https://s.shopee.com.br/70GSVaUJxC"
)


def _product(mid: int = 1, **kw: object) -> Offer:
    base = {
        "title": "Placa de Video Palit RTX 5070",
        "price": 467900,
        "text": PALIT,
        "coupon": ("ZAFADINHO10",),
        "at": NOW - timedelta(hours=1),
    }
    return offer(mid, **{**base, **kw})  # type: ignore[arg-type]


def _coupon(mid: int = 2, **kw: object) -> Offer:
    base = {
        "title": "Cupom Shopee",
        "price": None,
        "text": SHOPEE,
        "coupon": ("QIP98Q1ZXO",),
        "kind": OfferKind.coupon,
        "comparable": False,
        "store": "shopee",
        "at": NOW - timedelta(hours=1),
    }
    return offer(mid, **{**base, **kw})  # type: ignore[arg-type]


def _client(tmp_path: Path, *offers: Offer) -> TestClient:
    tmp_path.mkdir(parents=True, exist_ok=True)
    client = make_client(tmp_path, clock=FakeClock(NOW))
    conn = connect(tmp_path / "web.db")
    try:
        put(conn, *offers)
    finally:
        conn.close()
    return client


class _Buttons(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.copy: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "button" and "data-copy" in dict(attrs):
            self.copy.append(dict(attrs))


def _copy_buttons(page: str) -> list[dict[str, str | None]]:
    parser = _Buttons()
    parser.feed(page)
    return parser.copy


def _section(page: str, marker: str) -> str:
    start = page.index(marker)
    return page[start : page.index("</section>", start)]


def test_product_card_reads_com_cupom_and_has_one_copy_button_per_code(tmp_path: Path) -> None:
    client = _client(tmp_path, _product(coupon=("ZAFADINHO10", "KORUJAO")))
    page = client.get("/").text
    assert "R$ 4.679,00" in page and "com cupom" in page
    buttons = _copy_buttons(page)
    assert [(b["data-copy"], b["aria-label"], b["type"]) for b in buttons] == [
        ("ZAFADINHO10", "Copiar cupom ZAFADINHO10", "button"),
        ("KORUJAO", "Copiar cupom KORUJAO", "button"),
    ]
    assert all("coupon-code" in (b["class"] or "") for b in buttons)
    assert "content_copy" in page
    assert 'aria-live="polite"' in page


def test_card_without_codes_has_no_copy_button_or_cupom_label(tmp_path: Path) -> None:
    page = _client(tmp_path, offer(1, text="SSD por R$ 299")).get("/").text
    assert _copy_buttons(page) == []
    assert "com cupom" not in page


def test_coupon_card_layout_and_actions(tmp_path: Path) -> None:
    page = _client(tmp_path, _coupon(), _product(1)).get("/", params={"tipo": "cupons"}).text
    assert "R$ 10 OFF" in page
    assert "em compras a partir de R$ 40" in page
    assert [b["data-copy"] for b in _copy_buttons(page)] == ["QIP98Q1ZXO"]
    assert "Resgatar" in page and "https://x.test/resgate" in page
    assert "Acompanhar" not in page
    assert "Placa de Video" not in page  # product offers stay out of the coupon list


def test_coupon_card_falls_back_to_abrir_without_redeem_link(tmp_path: Path) -> None:
    conn_offer = _coupon()
    client = _client(tmp_path, conn_offer)
    conn = connect(tmp_path / "web.db")
    conn.execute("UPDATE offers SET redeem_link = NULL")
    conn.commit()
    conn.close()
    page = client.get("/", params={"tipo": "cupons"}).text
    assert "Resgatar" not in page and "Abrir" in page


def test_main_list_excludes_coupons_and_active_strip_shows_them(tmp_path: Path) -> None:
    client = _client(tmp_path, _product(1), _coupon(2), _coupon(3, at=NOW - timedelta(hours=8)))
    page = client.get("/").text
    assert "Cupons ativos" in page
    strip = _section(page, "Cupons ativos")
    assert "R$ 10 OFF" in strip
    assert strip.count('class="offer offer-coupon') == 1  # the 8 h old coupon is gone
    results = page[page.index('id="feed"') :]
    assert "Placa de Video" in results
    assert "offer-coupon" not in results


def test_strip_is_hidden_without_active_coupons_or_when_filtered(tmp_path: Path) -> None:
    client = _client(tmp_path, _product(1), _coupon(2, at=NOW - timedelta(hours=9)))
    assert "Cupons ativos" not in client.get("/").text
    client = _client(tmp_path / "b", _product(1), _coupon(2))
    assert "Cupons ativos" in client.get("/").text
    assert "Cupons ativos" not in client.get("/", params={"q": "placa"}).text
    assert "Cupons ativos" not in client.get("/", params={"tipo": "cupons"}).text
    assert "Cupons ativos" not in client.get("/", params={"store": "amazon"}).text


def test_cupons_filter_chip_is_checked_when_on(tmp_path: Path) -> None:
    client = _client(tmp_path, _coupon())
    off = client.get("/").text
    on = client.get("/", params={"tipo": "cupons"}).text
    chip = re.compile(r'<input[^>]*name="tipo"[^>]*value="cupons"[^>]*>')
    assert chip.search(off) is not None and "checked" not in chip.search(off).group(0)  # type: ignore[union-attr]
    assert "checked" in chip.search(on).group(0)  # type: ignore[union-attr]


def test_post_text_details_is_escaped_and_linkified(tmp_path: Path) -> None:
    text = "Oferta <script>alert(1)</script>\nhttps://cutt.ly/abc\njavascript:alert(1)"
    page = _client(tmp_path, offer(1, text=text)).get("/").text
    assert "Ver post completo" in page
    assert "<details" in page
    assert "&lt;script&gt;" in page and "<script>alert" not in page
    assert (
        '<a href="https://cutt.ly/abc" rel="noopener noreferrer" target="_blank">'
        "https://cutt.ly/abc</a>"
    ) in page


def test_purged_text_has_no_details(tmp_path: Path) -> None:
    page = _client(tmp_path, offer(1, text=None)).get("/").text
    assert "Ver post completo" not in page


def test_product_match_row_has_copy_button(tmp_path: Path) -> None:
    client = make_client(tmp_path, clock=FakeClock(NOW))
    assert (
        client.post(
            "/wishes/new",
            data={
                "name": "Placa",
                "required_terms": "placa",
                "excluded_terms": "",
                "max_price": "6000,00",
            },
        ).status_code
        == 303
    )
    conn = connect(make_settings(tmp_path).db_path)
    try:
        o = _product(1)
        put(conn, o)
        SqliteOfferRepository(conn).add_match(match(1, o, MatchSource.live))
    finally:
        conn.close()
    page = client.get("/wishes/1").text
    assert [b["data-copy"] for b in _copy_buttons(page)] == ["ZAFADINHO10"]
    assert "com cupom" in page


TIERS = (
    CouponTier("R$ 90 OFF", 69900),
    CouponTier("10% OFF", 7900),
    CouponTier("10% OFF", 14900),
    CouponTier("25% OFF", 100),
    CouponTier("30% OFF", 100),
)
CODES = ("SEMPRESAUDE", "PROMOSML", "CLIENTESTOP", "GARANTAJA", "OFERTABOA")


def _multi_tier(mid: int = 3) -> Offer:
    return _coupon(
        mid,
        title="Cupom Mercado Livre",
        coupon=CODES,
        store="mercadolivre",
        coupon_tiers=TIERS,
        coupon_discount="R$ 90 OFF",
    )


def _card_html(page: str, marker: str) -> str:
    start = page.index(marker)
    return page[start : page.index("</article>", start)]


def test_multi_tier_card_leads_with_the_best_tier_and_lists_three(tmp_path: Path) -> None:
    page = _client(tmp_path, _multi_tier()).get("/", params={"tipo": "cupons"}).text
    card = _card_html(page, 'class="offer offer-coupon')
    assert "Até R$ 90 OFF" in card
    assert card.count("<li>") == 3
    assert "R$ 90 OFF em R$ 699" in card and "10% OFF em R$ 79" in card
    assert "+2 condições" in card
    assert len(_copy_buttons(card)) == 5  # the full card keeps every code
    assert "Ver post completo" in card


def test_single_tier_card_is_unchanged(tmp_path: Path) -> None:
    page = _client(tmp_path, _coupon()).get("/", params={"tipo": "cupons"}).text
    card = _card_html(page, 'class="offer offer-coupon')
    assert "R$ 10 OFF" in card and "Até" not in card
    assert "<li" not in card and "em compras a partir de R$ 40" in card


def test_strip_card_is_compact(tmp_path: Path) -> None:
    page = _client(tmp_path, _multi_tier()).get("/").text
    strip = _section(page, "Cupons ativos")
    assert len(_copy_buttons(strip)) == 2
    assert 'class="coupon-more"' in strip and ">+3<" in strip
    assert "/?tipo=cupons#cupom-1-3" in strip
    assert "Ver post completo" not in strip
    assert strip.count("<li>") == 2 and "+3 condições" in strip
    assert 'id="cupom-1-3"' not in page  # anchors live on the full cards only


def test_full_card_carries_the_anchor_the_strip_links_to(tmp_path: Path) -> None:
    page = _client(tmp_path, _multi_tier()).get("/", params={"tipo": "cupons"}).text
    assert 'id="cupom-1-3"' in page


def test_coupon_card_does_not_repeat_the_discount_in_its_title(tmp_path: Path) -> None:
    repeat = _coupon(4, title="Cupom KaBuM em produtos selecionados - 11% OFF", store="kabum")
    bare = _coupon(5, title="Cupom Shopee")
    page = _client(tmp_path, repeat, bare).get("/", params={"tipo": "cupons"}).text
    assert 'class="offer-title">em produtos selecionados<' in page
    assert "Cupom KaBuM" not in page
    assert page.count('class="offer-title"') == 1  # "Cupom Shopee" leaves nothing to show
