"""Magalu: numeric ids; no stable product page and no body is read."""

import re
from dataclasses import dataclass

from velkgram.offers.domain.stores.base import BaseStore
from velkgram.offers.domain.urls import strip_query

_ID = re.compile(r"/p/(\d+)(?:[/?#]|$)")


@dataclass(frozen=True, slots=True)
class Magalu(BaseStore):
    def product_id_in_url(self, url: str) -> str | None:
        m = _ID.search(strip_query(url))
        return m.group(1) if m else None


MAGALU = Magalu(
    slug="magalu",
    name="Magalu",
    domains=("magazineluiza.com.br", "magazinevoce.com.br", "magalu.com"),
    body_budget=0,
    identifies_products=True,
)
