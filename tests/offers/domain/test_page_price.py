import json

import pytest

from velkgram.offers.domain.page_price import jsonld_image, jsonld_price
from velkgram.offers.domain.stores import STORES
from velkgram.offers.domain.stores.amazon import amazon_price


def _ld(data: object) -> str:
    return f'<html><script type="application/ld+json">{json.dumps(data)}</script></html>'


def _product(price: object, **extra: object) -> dict[str, object]:
    return {"@type": "Product", "offers": {"@type": "Offer", "price": price}, **extra}


@pytest.mark.parametrize(
    ("price", "cents"),
    [
        (418.41, 41841),
        ("1960.8", 196080),
        (99.99, 9999),
        (10499, 1049900),
        ("0", None),
        ("x", None),
    ],
)
def test_jsonld_price_is_exact_cents(price: object, cents: int | None) -> None:
    assert jsonld_price(_ld(_product(price))) == cents


def test_jsonld_finds_the_product_inside_a_graph() -> None:
    assert jsonld_price(_ld({"@graph": [{"@type": "WebSite"}, _product("50.00")]})) == 5000


def test_jsonld_offers_list_with_one_price_is_that_price() -> None:
    offers = [{"price": "10.00"}, {"price": "10.00"}]
    assert jsonld_price(_ld({"@type": "Product", "offers": offers})) == 1000


def test_jsonld_offers_that_disagree_are_unknown() -> None:
    offers = [{"price": "10.00"}, {"price": "12.00"}]
    assert jsonld_price(_ld({"@type": "Product", "offers": offers})) is None


def test_jsonld_aggregate_offer_uses_low_price() -> None:
    offer = {"@type": "AggregateOffer", "lowPrice": "7.50"}
    assert jsonld_price(_ld({"@type": "Product", "offers": offer})) == 750


def test_jsonld_ignores_broken_blocks_and_non_products() -> None:
    body = '<script type="application/ld+json">{oops</script>' + _ld({"@type": "Organization"})
    assert jsonld_price(body) is None


def test_jsonld_image_takes_the_first_of_a_list_or_an_object() -> None:
    assert jsonld_image(_ld(_product(1, image=["https://i/a.jpg", "https://i/b.jpg"]))) == (
        "https://i/a.jpg"
    )
    assert jsonld_image(_ld(_product(1, image={"url": "https://i/c.jpg"}))) == "https://i/c.jpg"
    assert jsonld_image(_ld(_product(1))) is None


def _amazon(*shown: str, block: str = "corePriceDisplay_desktop_feature_div") -> str:
    spans = "".join(f'<span class="a-offscreen">{t}</span>' for t in shown)
    other = '<div id="other"><span class="a-offscreen">R$\xa01,02</span></div>'
    return f'{other}<div id="{block}">{spans}'


def test_amazon_reads_the_main_price_block_not_the_first_price_on_the_page() -> None:
    assert amazon_price(_amazon("R$\xa010.499,00", "R$\xa012.000,00")) == 1049900


def test_amazon_price_without_a_space_and_with_the_old_block_name() -> None:
    assert amazon_price(_amazon("R$899,99", block="corePrice_feature_div")) == 89999


def test_amazon_without_a_price_block_is_unknown() -> None:
    assert amazon_price('<span class="a-offscreen">R$ 10,00</span>') is None
    assert amazon_price(_amazon(" ")) is None


def test_page_price_picks_the_reader_by_store() -> None:
    assert STORES["kabum"].page_price(_ld(_product("20.00"))) == 2000
    assert STORES["amazon"].page_price(_amazon("R$ 30,00")) == 3000
