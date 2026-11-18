"""KaBuM!: numeric ids; its pages carry schema.org JSON-LD, which the default reads."""

import re
from dataclasses import dataclass

from velkgram.offers.domain.link_types import KB
from velkgram.offers.domain.stores.base import BaseStore
from velkgram.offers.domain.urls import strip_query

_ID = re.compile(r"/produto/(\d+)")


@dataclass(frozen=True, slots=True)
class Kabum(BaseStore):
    def product_id_in_url(self, url: str) -> str | None:
        m = _ID.search(strip_query(url))
        return m.group(1) if m else None

    def product_url(self, product_id: str) -> str | None:
        return f"https://www.kabum.com.br/produto/{product_id}"


KABUM = Kabum(
    slug="kabum",
    name="KaBuM!",
    domains=("kabum.com.br",),
    body_budget=16 * KB,
    identifies_products=True,
)
