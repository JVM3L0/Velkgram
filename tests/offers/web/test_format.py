from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest

from velkgram.offers import OfferCard
from velkgram.offers.web.format import (
    STORE_NAMES,
    follow_url,
    format_price,
    parse_price_cents,
    relative_time,
    safe_href,
)

SP = ZoneInfo("America/Sao_Paulo")
POSTED = datetime(2026, 11, 5, 2, 0, tzinfo=UTC)


def _card(title: str = "SSD Kingston 1TB NV2", price: int | None = 29990) -> OfferCard:
    return OfferCard(1, 1, POSTED, title, price, "amazon", None, False, False, False, 0)


def test_relative_time_uses_app_timezone() -> None:
    assert relative_time(POSTED, POSTED + timedelta(minutes=30), SP) == "há 30 min"
    assert relative_time(POSTED, datetime(2026, 11, 5, 3, 30, tzinfo=UTC), SP) == "ontem 23:00"


def test_relative_time_buckets() -> None:
    assert relative_time(POSTED, POSTED + timedelta(seconds=59), SP) == "agora"
    assert relative_time(POSTED, POSTED - timedelta(minutes=5), SP) == "agora"
    noon = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    assert relative_time(noon, noon + timedelta(hours=2, minutes=10), SP) == "há 2 h"
    assert relative_time(POSTED, POSTED + timedelta(days=3), SP) == "04/11 23:00"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x.test/a", "https://x.test/a"),
        ("http://x.test/a", "http://x.test/a"),
        ("javascript:alert(1)", None),
        ("tg://x", None),
        ("data:text/html,x", None),
        (None, None),
    ],
)
def test_safe_href(url: str | None, expected: str | None) -> None:
    assert safe_href(url) == expected


def test_follow_url_prefills_terms_and_price() -> None:
    url = follow_url(_card())
    parts = urlsplit(url)
    assert parts.path == "/wishes/new"
    query = parse_qs(parts.query)
    assert query["name"] == ["SSD Kingston 1TB NV2"]
    assert sorted(query["required"]) == ["1tb", "kingston", "nv2", "ssd"]
    assert query["max_price"] == ["299,90"]
    assert "max_price=299%2C90" in url


def test_follow_url_omits_unknown_price() -> None:
    assert "max_price" not in follow_url(_card(price=None))


def test_price_parsing_and_formatting() -> None:
    assert parse_price_cents("1.299,90") == 129990
    assert parse_price_cents("abc") is None
    assert format_price(129900) == "1299,00"


def test_store_names_reuse_titles() -> None:
    assert STORE_NAMES["mercadolivre"] == "Mercado Livre"
