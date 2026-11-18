"""AliExpress: ids sit in a nested query string; the affiliate click is fetched for one hop."""

import re
from dataclasses import dataclass
from urllib.parse import unquote

from velkgram.offers.domain.link_types import FetchPlan
from velkgram.offers.domain.stores.base import BaseStore

_PRODUCT_ID = re.compile(r"productIds?=(\d{10,20})")
_ITEM = re.compile(r"/item/(?:[^/?#]*/)?(\d{10,20})\.html")
_UNQUOTE_ROUNDS = 3
_CLICK = "s.click.aliexpress.com"


@dataclass(frozen=True, slots=True)
class AliExpress(BaseStore):
    def product_id_in_url(self, url: str) -> str | None:
        # The id sits in a (possibly url-encoded, nested) query string.
        text = url
        for _ in range(_UNQUOTE_ROUNDS + 1):
            m = _PRODUCT_ID.search(text) or _ITEM.search(text)
            if m:
                return m.group(1)
            decoded = unquote(text)
            if decoded == text:
                break
            text = decoded
        return None

    def product_url(self, product_id: str) -> str | None:
        return f"https://pt.aliexpress.com/item/{product_id}.html"


ALIEXPRESS = AliExpress(
    slug="aliexpress",
    name="AliExpress",
    domains=("aliexpress.com", _CLICK, "a.aliexpress.com"),
    body_budget=0,
    short_hosts=frozenset({_CLICK}),
    short_plan=FetchPlan(follow=False, first_hop_only=True, body_budget=0),
    identifies_products=True,
)
