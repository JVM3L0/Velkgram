"""Shopee: `shop.item` ids; its pages are a SPA, so no body is read."""

import re
from dataclasses import dataclass

from velkgram.offers.domain.link_types import FetchPlan
from velkgram.offers.domain.stores.base import BaseStore
from velkgram.offers.domain.urls import strip_query

_PATH = re.compile(r"/(\d+)/(\d+)(?:[/?#]|$)")
_SLUG = re.compile(r"-i\.(\d+)\.(\d+)")


@dataclass(frozen=True, slots=True)
class Shopee(BaseStore):
    def product_id_in_url(self, url: str) -> str | None:
        path = strip_query(url)
        m = _SLUG.search(path) or _PATH.search(path)
        return f"{m.group(1)}.{m.group(2)}" if m else None

    def product_url(self, product_id: str) -> str | None:
        shop, _, item = product_id.partition(".")
        return f"https://shopee.com.br/product/{shop}/{item}" if shop and item else None


SHOPEE = Shopee(
    slug="shopee",
    name="Shopee",
    domains=("shopee.com.br", "s.shopee.com.br", "shope.ee"),
    body_budget=0,
    short_hosts=frozenset({"s.shopee.com.br"}),
    short_plan=FetchPlan(follow=True, first_hop_only=False, body_budget=0),
    identifies_products=True,
)
