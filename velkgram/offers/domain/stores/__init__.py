"""Per-store rules of the offers domain: the `Store` contract, one module per store with its own
rules, the registry (`STORES`) and link detection (`store_of`)."""

from velkgram.offers.domain.stores.base import BaseStore, Store
from velkgram.offers.domain.stores.posts import main_link, product_link
from velkgram.offers.domain.stores.registry import STORES, store_of

__all__ = ["STORES", "BaseStore", "Store", "main_link", "product_link", "store_of"]
