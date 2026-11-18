"""What a followed link tells us about the product (pure).

The rules that differ per store live in `stores/`; this module only asks the store behind a link.
"""

from velkgram.offers.domain.link_types import (
    KB,
    FetchOutcome,
    FetchPlan,
    Kind,
    LinkInfo,
    Status,
)
from velkgram.offers.domain.page_html import TITLE_MAX, og_page
from velkgram.offers.domain.stores import STORES, store_of
from velkgram.offers.domain.stores.base import DEFAULT_BUDGET
from velkgram.offers.domain.urls import host_of

__all__ = [
    "KB",
    "TITLE_MAX",
    "FetchOutcome",
    "FetchPlan",
    "Kind",
    "LinkInfo",
    "Status",
    "budget_for",
    "fetch_plan",
    "resolve",
    "resolve_url_only",
]

# Link shorteners that belong to no store.
_SHORTENERS = frozenset({"cutt.ly", "tidd.ly", "bit.ly", "go.promotom.com.br"})
# Still being the final host means the link was not expanded.
_SHORT_HOSTS = _SHORTENERS.union(*(s.short_hosts for s in STORES.values()))


def _bare(host: str) -> str:
    return host.removeprefix("www.")


def fetch_plan(url: str) -> FetchPlan:
    host = _bare(host_of(url))
    slug = store_of(url)
    if slug is not None and (plan := STORES[slug].fetch_plan(url, host)) is not None:
        return plan
    if host in _SHORTENERS:
        return FetchPlan(follow=True, first_hop_only=False, body_budget=None)
    return FetchPlan(follow=True, first_hop_only=False, body_budget=DEFAULT_BUDGET)


def budget_for(url: str) -> int:
    """Body budget in bytes by the host of `url` (the final hop)."""
    slug = store_of(url)
    return STORES[slug].body_budget if slug is not None else DEFAULT_BUDGET


def resolve_url_only(url: str) -> LinkInfo | None:
    """Store and id from the URL alone, as a product with no title; None when unknown."""
    slug = store_of(url)
    if slug is None:
        return None
    product_id = STORES[slug].product_id_in_url(url)
    if product_id is None:
        return None
    return LinkInfo(slug, product_id, None, None, "product")


def resolve(original_url: str, outcome: FetchOutcome) -> LinkInfo:
    """What a fetch outcome says about the link (spec §5.3). Never raises on bad input."""
    candidates = (outcome.final_url, *outcome.hops, original_url)
    slug = next((s for url in candidates if (s := store_of(url))), None)
    store = STORES[slug] if slug is not None else None
    product_id = None
    if store is not None and store.identifies_products:
        product_id = next((i for url in candidates if (i := store.product_id_in_url(url))), None)

    body = outcome.body
    read_ok = isinstance(outcome.status, int) and outcome.status < 400
    if body is not None and not read_ok:
        body = None

    if store is not None and body is not None:
        if store.is_blocked(body):
            return LinkInfo(slug, product_id, None, None, "unknown")
        if product_id is None:
            product_id = store.product_id_in_body(body)

    if store is not None and product_id is not None:
        if body is None:
            return LinkInfo(slug, product_id, None, None, "product")
        title, image = store.page_details(body)
        return LinkInfo(slug, product_id, title, image, "product", store.page_price(body))

    final_host = _bare(host_of(outcome.final_url))
    if store is not None and store.identifies_products:
        # A short link that never redirected tells nothing: retry it, it is not a non-product.
        unexpanded = final_host in _SHORT_HOSTS
        return LinkInfo(
            slug, None, None, None, "not_product" if read_ok and not unexpanded else "unknown"
        )

    if body is None or final_host in _SHORTENERS:
        return LinkInfo(slug, None, None, None, "unknown")
    title, image = og_page(body, strip_price=False)
    return LinkInfo(slug, None, title, image, "unknown")
