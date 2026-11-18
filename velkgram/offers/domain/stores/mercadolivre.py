"""Mercado Livre: MLB ids (also found in the page body) and titles that end in the price."""

import re
from dataclasses import dataclass

from velkgram.offers.domain.link_types import KB, FetchPlan
from velkgram.offers.domain.stores.base import BaseStore
from velkgram.offers.domain.urls import strip_query

_MLB = re.compile(r"MLB-?(\d{6,})")
_ITEM_ID = re.compile(r'"item_id"\s*:\s*"(MLB\d+)"')
_BUDGET = 512 * KB


@dataclass(frozen=True, slots=True)
class MercadoLivre(BaseStore):
    def product_id_in_url(self, url: str) -> str | None:
        m = _MLB.search(strip_query(url))
        return f"MLB{m.group(1)}" if m else None

    def product_id_in_body(self, body: str) -> str | None:
        m = _ITEM_ID.search(body)
        return m.group(1) if m else None

    def product_url(self, product_id: str) -> str | None:
        return f"https://www.mercadolivre.com.br/p/{product_id}"


MERCADOLIVRE = MercadoLivre(
    slug="mercadolivre",
    name="Mercado Livre",
    domains=("mercadolivre.com.br", "mercadolivre.com", "mercadolibre.com", "meli.la"),
    body_budget=_BUDGET,
    short_hosts=frozenset({"meli.la"}),
    short_plan=FetchPlan(follow=True, first_hop_only=False, body_budget=_BUDGET),
    identifies_products=True,
    strip_title_price=True,
)
