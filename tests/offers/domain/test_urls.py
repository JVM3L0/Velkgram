import pytest

from velkgram.offers.domain.urls import host_of, is_safe_https_url, is_safe_url, strip_query
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
