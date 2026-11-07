import pytest

from velkgram.offers.domain.urls import (
    host_of,
    is_safe_https_url,
    is_safe_url,
    product_url,
    real_product_url,
    strip_query,
)
from velkgram.offers.web.format import safe_href


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://a.com/p/1?tag=secret&x=1#frag", "https://a.com/p/1"),
        ("https://a.com/p/1#frag", "https://a.com/p/1"),
        ("https://a.com/p/1", "https://a.com/p/1"),
        ("https://a.com?tag=x", "https://a.com"),
        ("not a url?x=1", "not a url"),
        ("http://[::1?x=1", "http://[::1"),
        ("", ""),
    ],
)
def test_strip_query_drops_query_and_fragment(url: str, expected: str) -> None:
    assert strip_query(url) == expected


@pytest.mark.parametrize(
    ("url", "http_ok", "https_ok"),
    [
        ("https://a.com", True, True),
        ("HTTPS://a.com", True, True),
        ("http://a.com", True, False),
        ("javascript:alert(1)", False, False),
        ("data:text/html,x", False, False),
        ("tg://resolve?domain=x", False, False),
        ("//a.com/x", False, False),
        ("http://[::1", False, False),
        ("", False, False),
        (None, False, False),
    ],
)
def test_safe_url_predicates(url: str | None, http_ok: bool, https_ok: bool) -> None:
    assert is_safe_url(url) is http_ok
    assert is_safe_https_url(url) is https_ok


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://WWW.Amazon.com.br/dp/B0", "www.amazon.com.br"),
        ("https://meli.la/abc", "meli.la"),
        ("https://a.com:8443/x", "a.com"),
        ("javascript:alert(1)", ""),
        ("http://[::1", ""),
        ("", ""),
    ],
)
def test_host_of_is_lowercase_or_empty(url: str, expected: str) -> None:
    assert host_of(url) == expected


@pytest.mark.parametrize(
    "url", ["https://a.com/x?y=1", "http://a.com", "javascript:x", "tg://x", None, "http://[::1"]
)
def test_safe_href_keeps_its_behavior(url: str | None) -> None:
    expected = url if url is not None and url.startswith(("http://a", "https://a")) else None
    assert safe_href(url) == expected


@pytest.mark.parametrize(
    ("store", "pid", "expected"),
    [
        ("amazon", "B0C8814GKB", "https://www.amazon.com.br/dp/B0C8814GKB"),
        ("mercadolivre", "MLB62870034", "https://www.mercadolivre.com.br/p/MLB62870034"),
        ("kabum", "123456", "https://www.kabum.com.br/produto/123456"),
        ("shopee", "898761179.44718674582", "https://shopee.com.br/product/898761179/44718674582"),
        ("aliexpress", "1005006571234567", "https://pt.aliexpress.com/item/1005006571234567.html"),
        ("magalu", "abc123", None),
        (None, "abc123", None),
        ("amazon", None, None),
    ],
)
def test_product_url_per_store(store: str | None, pid: str | None, expected: str | None) -> None:
    assert product_url(store, pid) == expected


def test_real_product_url_falls_back_to_final_url() -> None:
    final = "https://www.magazineluiza.com.br/x/p/abc123/"
    assert real_product_url("magalu", "abc123", "product", final) == final


def test_real_product_url_prefers_built_url() -> None:
    got = real_product_url("amazon", "B0C8814GKB", "product", "https://amzn.to/x")
    assert got == "https://www.amazon.com.br/dp/B0C8814GKB"


def test_real_product_url_none_unless_product_kind() -> None:
    assert real_product_url("amazon", "B0C8814GKB", "not_product", "https://a.com/p") is None
    assert real_product_url("amazon", "B0C8814GKB", None, None) is None


def test_real_product_url_rejects_unsafe_final_url() -> None:
    assert real_product_url("other", None, "product", "http://x.com/p") is None
    assert real_product_url("other", None, "product", None) is None
