"""What a store must answer (`Store`) and what a plain store answers by default (`BaseStore`).

A store with no special rules is a `BaseStore(...)` of pure data. A store with its own rules
subclasses `BaseStore` and overrides only those methods; nothing else in the codebase branches on
the store's slug.
"""

from dataclasses import dataclass
from typing import Protocol

from velkgram.offers.domain.link_types import KB, FetchPlan
from velkgram.offers.domain.page_html import clean_image, og_page
from velkgram.offers.domain.page_price import jsonld_image, jsonld_price

DEFAULT_BUDGET = 64 * KB
# A short link is followed to its target; the body budget is then decided at the final hop.
FOLLOW_SHORT = FetchPlan(follow=True, first_hop_only=False, body_budget=None)


class Store(Protocol):
    """The contract the link rules, the URL builders and the title rules rely on."""

    @property
    def slug(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def domains(self) -> tuple[str, ...]: ...
    @property
    def short_hosts(self) -> frozenset[str]:
        """Hosts that, as the final one, mean the short link was never expanded."""
        ...

    @property
    def body_budget(self) -> int:
        """Bytes of a page of this store worth reading."""
        ...

    @property
    def identifies_products(self) -> bool:
        """Whether a product id can be read, so a link without one is not a product."""
        ...

    def fetch_plan(self, url: str, host: str) -> FetchPlan | None:
        """How to fetch `url` (its `host` minus "www."); None when the store has no special case."""
        ...

    def product_id_in_url(self, url: str) -> str | None: ...
    def product_id_in_body(self, body: str) -> str | None: ...
    def is_blocked(self, body: str) -> bool:
        """Whether the page is an anti-bot wall instead of the product."""
        ...

    def page_details(self, body: str) -> tuple[str | None, str | None]:
        """Title and image of the product page."""
        ...

    def page_price(self, body: str) -> int | None: ...
    def product_url(self, product_id: str) -> str | None:
        """The stable product page for `product_id`; None when the store has none."""
        ...


@dataclass(frozen=True, slots=True)
class BaseStore:
    slug: str
    name: str
    domains: tuple[str, ...]
    body_budget: int = DEFAULT_BUDGET
    short_hosts: frozenset[str] = frozenset()
    short_plan: FetchPlan = FOLLOW_SHORT
    identifies_products: bool = False
    strip_title_price: bool = False  # the page title ends in " - R$ 99,90"

    def fetch_plan(self, url: str, host: str) -> FetchPlan | None:
        return short_host_plan(self, host)

    def product_id_in_url(self, url: str) -> str | None:
        return None

    def product_id_in_body(self, body: str) -> str | None:
        return None

    def is_blocked(self, body: str) -> bool:
        return False

    def page_details(self, body: str) -> tuple[str | None, str | None]:
        title, image = og_page(body, strip_price=self.strip_title_price)
        return title, image or clean_image(jsonld_image(body))

    def page_price(self, body: str) -> int | None:
        return jsonld_price(body)

    def product_url(self, product_id: str) -> str | None:
        return None


def short_host_plan(store: BaseStore, host: str) -> FetchPlan | None:
    return store.short_plan if host in store.short_hosts else None
