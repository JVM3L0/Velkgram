"""Real HTTP cursors (next_url, _cursor_text round trip) over rows that all share one posted_at."""

import html
import re
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from tests.offers.adapters._queries_helpers import T0, match, offer, put
from tests.offers.web.test_coupons_ui import NOW
from tests.offers.web.test_coupons_ui import _client as coupons_client
from tests.offers.web.test_feed_page import _client as feed_client
from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository
from velkgram.offers.domain.models import Offer, OfferKind
from velkgram.shared.db import connect

KEYS = [(c, m) for c in (1, 2, 3) for m in range(1, 31)]  # 90 rows: three full pages
NEXT = re.compile(r'hx-get="([^"]+)" hx-trigger="revealed, click"')


def _walk(client: TestClient, first: str, found: Callable[[str], set[str]]) -> list[set[str]]:
    pages: list[set[str]] = []
    url: str | None = first
    for _ in range(10):
        assert url is not None
        page = (
            client.get(url, headers={"HX-Request": "true"}).text if pages else client.get(url).text
        )
        pages.append(found(page))
        nxt = NEXT.search(page)
        if nxt is None:
            return pages
        url = html.unescape(nxt.group(1))
    raise AssertionError("pagination never ended")


def _assert_exactly_once(pages: list[set[str]], expected: set[str]) -> None:
    assert len(pages) == 3
    assert sum(len(p) for p in pages) == len(expected)
    assert set().union(*pages) == expected


def test_feed_http_cursors_with_identical_posted_at(tmp_path: Path) -> None:
    offers = [offer(m, channel_id=c, at=T0, title=f"Item {c}x{m}x") for c, m in KEYS]
    client = feed_client(tmp_path, *offers)

    def found(page: str) -> set[str]:
        return set(re.findall(r"Item \d+x\d+x", page))

    pages = _walk(client, "/", found)
    _assert_exactly_once(pages, {f"Item {c}x{m}x" for c, m in KEYS})


def test_feed_http_cursors_keep_the_store_filter(tmp_path: Path) -> None:
    amazon = [offer(m, channel_id=1, at=T0, title=f"Item 1x{m}x") for m in range(1, 66)]
    other = [
        offer(m, channel_id=2, at=T0, title=f"Item 2x{m}x", store="kabum") for m in range(1, 9)
    ]
    client = feed_client(tmp_path, *amazon, *other)

    def found(page: str) -> set[str]:
        return set(re.findall(r"Item \d+x\d+x", page))

    pages: list[set[str]] = []
    url: str | None = "/?store=amazon"
    while url:
        page = client.get(url).text
        pages.append(found(page))
        nxt = NEXT.search(page)
        url = html.unescape(nxt.group(1)) if nxt else None
    assert len(pages) == 3
    assert set().union(*pages) == {f"Item 1x{m}x" for m in range(1, 66)}
    assert sum(len(p) for p in pages) == 65


def test_coupons_http_cursors_with_identical_posted_at_and_store_filter(tmp_path: Path) -> None:
    coupons: list[Offer] = [
        offer(
            m,
            channel_id=c,
            at=NOW,
            title="Cupom",
            price=None,
            coupon=("CODE",),
            kind=OfferKind.coupon,
            comparable=False,
            store="shopee",
        )
        for c, m in KEYS
    ]
    coupons.append(
        offer(
            500,
            channel_id=9,
            at=NOW,
            kind=OfferKind.coupon,
            price=None,
            coupon=("OUT",),
            comparable=False,
            store="amazon",
        )
    )
    client = coupons_client(tmp_path, *coupons)

    def found(page: str) -> set[str]:
        return set(re.findall(r'id="(cupom-\d+-\d+)"', page))

    pages = _walk(client, "/cupons?loja=shopee", found)
    _assert_exactly_once(pages, {f"cupom-{c}-{m}" for c, m in KEYS})


def test_product_matches_http_cursors_with_identical_posted_at(tmp_path: Path) -> None:
    client = feed_client(tmp_path)
    created = client.post(
        "/wishes/new",
        data={"name": "Item", "required_terms": "item", "excluded_terms": "", "max_price": "3,00"},
    )
    assert created.status_code == 303
    conn = connect(tmp_path / "web.db")
    try:
        offers = [offer(m, channel_id=c, at=T0, title=f"Item {c}x{m}x") for c, m in KEYS]
        put(conn, *offers)
        repo = SqliteOfferRepository(conn)
        for o in offers:
            repo.add_match(match(1, o))
    finally:
        conn.close()

    def found(page: str) -> set[str]:
        return set(re.findall(r"Item \d+x\d+x", page))

    pages = _walk(client, "/wishes/1", found)
    _assert_exactly_once(pages, {f"Item {c}x{m}x" for c, m in KEYS})
