"""Every known store, in match order, and detection of the store behind a link (pure, no network).

To support a new store: add a `BaseStore(...)` here, or a subclass in its own module when it has
rules of its own. Nothing else needs to change.
"""

from collections.abc import Mapping
from urllib.parse import urlsplit

from velkgram.offers.domain.stores.aliexpress import ALIEXPRESS
from velkgram.offers.domain.stores.amazon import AMAZON
from velkgram.offers.domain.stores.base import BaseStore, Store
from velkgram.offers.domain.stores.kabum import KABUM
from velkgram.offers.domain.stores.magalu import MAGALU
from velkgram.offers.domain.stores.mercadolivre import MERCADOLIVRE
from velkgram.offers.domain.stores.shopee import SHOPEE

_ALL: tuple[Store, ...] = (
    AMAZON,
    MERCADOLIVRE,
    SHOPEE,
    MAGALU,
    KABUM,
    ALIEXPRESS,
    BaseStore(slug="pichau", name="Pichau", domains=("pichau.com.br",)),
    BaseStore(slug="terabyte", name="Terabyte", domains=("terabyteshop.com.br",)),
    BaseStore(slug="casasbahia", name="Casas Bahia", domains=("casasbahia.com.br",)),
    BaseStore(slug="americanas", name="Americanas", domains=("americanas.com.br",)),
    BaseStore(slug="carrefour", name="Carrefour", domains=("carrefour.com.br",)),
    BaseStore(slug="netshoes", name="Netshoes", domains=("netshoes.com.br",)),
)
STORES: Mapping[str, Store] = {s.slug: s for s in _ALL}


def _host(url: str) -> str | None:
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    for prefix in ("www.", "m."):
        host = host.removeprefix(prefix)
    return host


def store_of(url: str) -> str | None:
    host = _host(url)
    if host is None:
        return None
    for store in STORES.values():
        if any(host == d or host.endswith("." + d) for d in store.domains):
            return store.slug
    return None
