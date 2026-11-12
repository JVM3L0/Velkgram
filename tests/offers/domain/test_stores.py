import pytest

from velkgram.offers.domain.stores import STORES, main_link, product_link, store_of

HOSTS = [(slug, host) for slug, hosts in STORES.items() for host in hosts]


@pytest.mark.parametrize(("slug", "host"), HOSTS)
@pytest.mark.parametrize("prefix", ["", "www.", "m."])
def test_every_known_host_maps_to_its_store(slug: str, host: str, prefix: str) -> None:
    assert store_of(f"https://{prefix}{host}/p/1?x=1") == slug


def test_uppercase_host_and_query() -> None:
    assert store_of("https://WWW.Amazon.com.br/dp/B0?tag=x") == "amazon"


def test_subdomain_of_registrable_domain() -> None:
    assert store_of("https://produto.mercadolivre.com.br/MLB-1") == "mercadolivre"


def test_lookalike_host_is_unknown() -> None:
    assert store_of("https://notamazon.com.br/x") is None


@pytest.mark.parametrize("url", ["https://bit.ly/a", "https://tidd.ly/a", "https://tinyurl.com/a"])
def test_generic_shorteners_are_unknown(url: str) -> None:
    assert store_of(url) is None


@pytest.mark.parametrize("url", ["http://[", "not a url"])
def test_malformed_url_is_unknown(url: str) -> None:
    assert store_of(url) is None


def test_main_link_prefers_known_store() -> None:
    links = ("https://bit.ly/a", "https://kabum.com.br/p/1")
    assert main_link(links) == "https://kabum.com.br/p/1"


def test_main_link_falls_back_to_first_then_none() -> None:
    assert main_link(("https://bit.ly/a", "https://tidd.ly/b")) == "https://bit.ly/a"
    assert main_link(()) is None


COUPONS = "https://s.shopee.com.br/30fk4tl3lu"
PRODUCT = "https://s.shopee.com.br/8fTr4C8eWt"


def test_product_link_is_the_one_labelled_link_produto_on_the_same_line() -> None:
    text = (
        "DJI Osmo Nano\n\nR$ 1522\n-Resgate todos os cupons desta página: "
        f"{COUPONS}\n\n-Link produto: {PRODUCT}\n\n-Anúncio"
    )
    assert product_link(text, (COUPONS, PRODUCT)) == PRODUCT


def test_product_link_reads_the_link_on_the_line_after_the_label() -> None:
    text = f"Creatina\n-Resgate todos os cupons desta página:\n{COUPONS}\n-Link produto:\n{PRODUCT}"
    assert product_link(text, (COUPONS, PRODUCT)) == PRODUCT


def test_product_link_accepts_link_do_produto_and_ignores_case_and_accents() -> None:
    assert product_link(f"LINK DO PRODUTO: {PRODUCT}", (PRODUCT,)) == PRODUCT


def test_product_link_is_none_without_the_label() -> None:
    text = f"Cupom Shopee\n-Resgate aqui: {COUPONS}\n-Link carrinho: {PRODUCT}"
    assert product_link(text, (COUPONS, PRODUCT)) is None
    assert product_link(None, (PRODUCT,)) is None
    assert product_link("sem links", ()) is None


def test_product_link_ignores_a_labelled_link_of_an_unknown_store() -> None:
    assert product_link("Link produto: https://bit.ly/abc", ("https://bit.ly/abc",)) is None


def test_product_link_does_not_borrow_a_link_from_a_later_line() -> None:
    text = f"-Link produto:\n-Anúncio\nhttps://bit.ly/x\n-Resgate aqui: {COUPONS}"
    assert product_link(text, ("https://bit.ly/x", COUPONS)) is None
