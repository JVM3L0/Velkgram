import pytest

from velkgram.offers.domain.stores import STORES, main_link, store_of

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
