from pathlib import Path

import pytest

from velkgram.offers.domain.links import (
    FetchOutcome,
    FetchPlan,
    LinkInfo,
    budget_for,
    fetch_plan,
    resolve,
    resolve_url_only,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "links"
KB = 1024


def page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def outcome(
    final: str,
    *,
    status: int | str = 200,
    body: str | None = None,
    hops: tuple[str, ...] = (),
) -> FetchOutcome:
    return FetchOutcome(
        final_url=final,
        hops=hops,
        status=status,  # type: ignore[arg-type]
        content_type="text/html" if body is not None else None,
        body=body,
        answered_by=final.split("/")[2] if "//" in final else "",
    )


def test_fixtures_are_small_and_scrubbed() -> None:
    for path in FIXTURES.glob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert len(text) <= 30 * KB
        assert "?" not in text.replace("?X", "")


# --- fetch plan / budgets --------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "plan"),
    [
        ("https://www.amazon.com.br/dp/B0ABCDEFGH?tag=x", FetchPlan(False, False, 512 * KB)),
        ("https://www.amazon.com.br/gp/aw/d/B0ABCDEFGH", FetchPlan(False, False, 512 * KB)),
        ("https://s.click.aliexpress.com/e/_abc", FetchPlan(False, True, 0)),
        ("https://s.shopee.com.br/abc", FetchPlan(True, False, 0)),
        ("https://meli.la/1abc", FetchPlan(True, False, 512 * KB)),
        ("https://cutt.ly/abc", FetchPlan(True, False, None)),
        ("https://tidd.ly/abc", FetchPlan(True, False, None)),
        ("https://bit.ly/abc", FetchPlan(True, False, None)),
        ("https://go.promotom.com.br/promocao/x", FetchPlan(True, False, None)),
        ("https://link.amazon/abc", FetchPlan(True, False, None)),
        ("https://www.pichau.com.br/x", FetchPlan(True, False, 64 * KB)),
        ("not a url", FetchPlan(True, False, 64 * KB)),
    ],
)
def test_fetch_plan(url: str, plan: FetchPlan) -> None:
    assert fetch_plan(url) == plan


@pytest.mark.parametrize(
    ("url", "budget"),
    [
        ("https://www.amazon.com.br/dp/B0ABCDEFGH", 512 * KB),
        ("https://www.mercadolivre.com.br/social/x", 512 * KB),
        ("https://www.kabum.com.br/produto/1", 16 * KB),
        ("https://www.aliexpress.com/x", 0),
        ("https://shopee.com.br/x/1/2", 0),
        ("https://www.magazineluiza.com.br/x", 0),
        ("https://www.pichau.com.br/x", 64 * KB),
        ("https://unknown.example/x", 64 * KB),
    ],
)
def test_budget_for_uses_final_host(url: str, budget: int) -> None:
    assert budget_for(url) == budget


# --- resolve: Amazon -------------------------------------------------------------------


def test_amazon_product_title_and_image() -> None:
    url = "https://www.amazon.com.br/dp/b0abcdefgh"
    info = resolve(url, outcome(url, body=page("amazon_product.html")))
    assert info == LinkInfo(
        store="amazon",
        product_id="B0ABCDEFGH",
        title="Stanley Garrafa Térmica Quick Flip Frost 710ml",
        image_url="https://m.media-amazon.com/images/I/51XjLYM-leL._AC_SL1500_.jpg",
        kind="product",
    )


def test_amazon_gp_url_gives_asin() -> None:
    url = "https://www.amazon.com.br/gp/aw/d/B0ABCDEFGH?tag=x"
    assert resolve(url, outcome(url)).product_id == "B0ABCDEFGH"


@pytest.mark.parametrize(
    ("raw", "title"),
    [
        ("Amazon.com.br: Fone XYZ", "Fone XYZ"),
        ("Fone XYZ : Amazon.com.br: Eletrônicos", "Fone XYZ"),
        ("Amazon.com.br: Fone XYZ : Amazon.com.br", "Fone XYZ"),
    ],
)
def test_amazon_title_prefix_and_suffix_are_stripped(raw: str, title: str) -> None:
    url = "https://www.amazon.com.br/dp/B0ABCDEFGH"
    body = f"<html><head><title>{raw}</title></head></html>"
    assert resolve(url, outcome(url, body=body)).title == title


def test_amazon_image_falls_back_to_data_old_hires() -> None:
    url = "https://www.amazon.com.br/dp/B0ABCDEFGH"
    body = '<title>X</title><img data-old-hires="https://m.media-amazon.com/i.jpg">'
    assert resolve(url, outcome(url, body=body)).image_url == "https://m.media-amazon.com/i.jpg"


def test_amazon_captcha_is_blocked() -> None:
    url = "https://www.amazon.com.br/dp/B0ABCDEFGH"
    info = resolve(url, outcome(url, body=page("amazon_captcha.html")))
    assert info.kind == "unknown"
    assert info.title is None
    assert info.image_url is None
    assert info.store == "amazon"


# --- resolve: other stores -------------------------------------------------------------


def test_kabum_og_tags() -> None:
    url = "https://www.kabum.com.br/produto/459144/placa-de-video"
    info = resolve("https://cutt.ly/x", outcome(url, hops=(url,), body=page("kabum_product.html")))
    assert info.store == "kabum"
    assert info.product_id == "459144"
    assert info.kind == "product"
    assert info.title is not None
    assert info.title.startswith("Placa de Vídeo RX 7600 Challenger")
    assert info.image_url is not None
    assert info.image_url.startswith("https://images.kabum.com.br/")


def test_mercadolivre_social_page_with_item_id() -> None:
    url = "https://www.mercadolivre.com.br/social/promotom?ref=X"
    info = resolve("https://meli.la/1abc", outcome(url, body=page("mercadolivre_social_item.html")))
    assert info == LinkInfo(
        store="mercadolivre",
        product_id="MLB5242231824",
        title="Gloss Fran By Franciny Ehlke Lip Honey Liphoney",
        image_url="https://http2.mlstatic.com/D_NQ_NP_675825-MLB93549007452_102025-P.webp",
        kind="product",
    )


def test_mercadolivre_social_page_without_item_id_is_not_product_and_has_no_image() -> None:
    url = "https://www.mercadolivre.com.br/social/promotom?ref=X"
    info = resolve(
        "https://meli.la/1abc", outcome(url, body=page("mercadolivre_social_noitem.html"))
    )
    assert info.kind == "not_product"
    assert info.product_id is None
    assert info.image_url is None
    assert info.title is None


@pytest.mark.parametrize(
    ("suffix", "title"),
    [
        (" - R$ 16,14", "Gloss"),
        (" - R$ 1.299,00", "Gloss"),
        (" - R$ 1.299", "Gloss"),
        (" - Edição R$ especial", "Gloss - Edição R$ especial"),
    ],
)
def test_mercadolivre_price_suffix_is_stripped(suffix: str, title: str) -> None:
    url = "https://www.mercadolivre.com.br/MLB-123456-gloss-_JM"
    body = f'<meta property="og:title" content="Gloss{suffix}">'
    info = resolve(url, outcome(url, body=body))
    assert info.product_id == "MLB123456"
    assert info.title == title


def test_aliexpress_product_id_from_first_hop() -> None:
    first = (
        "https://star.aliexpress.com/share/share.htm?redirectUrl="
        "https%3A%2F%2Fwww.aliexpress.com%2Fitem%2F1.html%3FproductId%3D1005006123456789%26x%3Dy"
    )
    final = "https://www.aliexpress.com/p/coin-index/index.html"
    info = resolve("https://s.click.aliexpress.com/e/_abc", outcome(final, hops=(first, final)))
    assert info.store == "aliexpress"
    assert info.product_id == "1005006123456789"
    assert info.kind == "product"
    assert info.title is None


def test_shopee_ids_from_path() -> None:
    url = "https://shopee.com.br/Fone-Bluetooth-i.123.456"
    assert resolve("https://s.shopee.com.br/x", outcome(url)).product_id == "123.456"
    url = "https://shopee.com.br/some-shop-slug/123/456"
    info = resolve("https://s.shopee.com.br/x", outcome(url, body=page("shopee_spa.html")))
    assert (info.store, info.product_id, info.kind) == ("shopee", "123.456", "product")
    assert info.title is None
    assert info.image_url is None


def test_magalu_403_still_gives_the_product_id() -> None:
    url = "https://www.magazineluiza.com.br/magazinex/p/240162700/"
    info = resolve("https://cutt.ly/x", outcome(url, status=403))
    assert info == LinkInfo("magalu", "240162700", None, None, "product")


def test_campaign_pages_are_not_products() -> None:
    amazon = "https://www.amazon.com.br/b/promocoes"
    assert resolve("https://link.amazon/x", outcome(amazon, body="<html></html>")).kind == (
        "not_product"
    )
    kabum = "https://www.kabum.com.br/promocao/ABC"
    info = resolve("https://go.promotom.com.br/promocao/x", outcome(kabum, body="<html></html>"))
    assert (info.store, info.kind) == ("kabum", "not_product")


def test_unknown_host_with_og_tags_keeps_the_title() -> None:
    url = "https://store.vivo.com.br/produto"
    body = '<meta property="og:title" content="  Celular &amp; Cia\n X "><meta property="og:image" content="https://i.example/a.jpg">'
    info = resolve(url, outcome(url, body=body))
    assert info == LinkInfo(None, None, "Celular & Cia X", "https://i.example/a.jpg", "unknown")


def test_cutt_ly_interstitial_is_unknown() -> None:
    url = "https://cutt.ly/abc"
    body = '<html><head><meta property="og:title" content="Cutt.ly"></head></html>'
    info = resolve(url, outcome(url, body=body))
    assert info == LinkInfo(None, None, None, None, "unknown")


@pytest.mark.parametrize("status", ["error", "invalid", "paused"])
def test_failed_fetch_is_unknown(status: str) -> None:
    url = "https://www.kabum.com.br/promocao/ABC"
    assert resolve(url, outcome(url, status=status)).kind == "unknown"


def test_blocked_known_store_without_id_is_unknown() -> None:
    url = "https://www.kabum.com.br/promocao/ABC"
    assert resolve(url, outcome(url, status=429)).kind == "unknown"


@pytest.mark.parametrize("image", ["http://i.example/a.jpg", "javascript:alert(1)", "//i/a.jpg"])
def test_unsafe_image_is_dropped(image: str) -> None:
    url = "https://store.vivo.com.br/p"
    body = f'<meta property="og:title" content="T"><meta property="og:image" content="{image}">'
    assert resolve(url, outcome(url, body=body)).image_url is None


def test_long_title_is_capped_at_200() -> None:
    url = "https://store.vivo.com.br/p"
    body = f'<meta property="og:title" content="{"a" * 250}">'
    title = resolve(url, outcome(url, body=body)).title
    assert title is not None
    assert len(title) == 200


@pytest.mark.parametrize(
    "body",
    [
        '<meta property="og:title" content="trunc',
        "<meta property=",
        "<meta " * 5000,
        "<title>unclosed",
        '\x00<meta property="og:title" content="a\x00b">\x00',
        f'<meta property="og:title" content="{"x" * 1_000_000}">',
        '<meta property="og:image" content="' + "h" * 1_000_000,
        "",
    ],
)
@pytest.mark.parametrize(
    "url",
    [
        "https://www.amazon.com.br/dp/B0ABCDEFGH",
        "https://www.mercadolivre.com.br/social/x",
        "https://store.vivo.com.br/p",
        "http://[::1",
        "",
    ],
)
def test_garbage_never_raises(url: str, body: str) -> None:
    info = resolve(url, outcome(url, body=body))
    assert info.kind in ("product", "not_product", "unknown")


# --- resolve_url_only ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://www.amazon.com.br/dp/b0abcdefgh?tag=x",
            LinkInfo("amazon", "B0ABCDEFGH", None, None, "product"),
        ),
        (
            "https://shopee.com.br/slug/123/456",
            LinkInfo("shopee", "123.456", None, None, "product"),
        ),
        (
            "https://www.magazineluiza.com.br/magazinex/p/240162700/",
            LinkInfo("magalu", "240162700", None, None, "product"),
        ),
        ("https://www.amazon.com.br/b/promocoes", None),
        ("https://cutt.ly/abc", None),
        ("http://[::1", None),
        ("", None),
    ],
)
def test_resolve_url_only(url: str, expected: LinkInfo | None) -> None:
    assert resolve_url_only(url) == expected
