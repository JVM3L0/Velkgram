"""The canonical product page of an enriched offer (pure)."""

from velkgram.offers.domain.stores import STORES
from velkgram.offers.domain.urls import is_safe_https_url


def product_url(store: str | None, product_id: str | None) -> str | None:
    """The canonical product page of a store item, or None when the store has no stable one."""
    if not store or not product_id or store not in STORES:
        return None
    return STORES[store].product_url(product_id)


def real_product_url(
    store: str | None, product_id: str | None, kind: str | None, final_url: str | None
) -> str | None:
    """The real product link of an enriched offer: built from the id, else the resolved URL."""
    if kind != "product":
        return None
    url = product_url(store, product_id) or final_url
    return url if is_safe_https_url(url) else None
