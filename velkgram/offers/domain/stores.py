"""Store detection from link hosts (pure, no network)."""

import unicodedata
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit

from velkgram.shared.text import URL_PATTERN

STORES: Mapping[str, tuple[str, ...]] = {
    "amazon": ("amazon.com.br", "amzn.to", "amzn.divulgador.link"),
    "mercadolivre": ("mercadolivre.com.br", "mercadolivre.com", "mercadolibre.com", "meli.la"),
    "shopee": ("shopee.com.br", "s.shopee.com.br", "shope.ee"),
    "magalu": ("magazineluiza.com.br", "magazinevoce.com.br", "magalu.com"),
    "kabum": ("kabum.com.br",),
    "aliexpress": ("aliexpress.com", "s.click.aliexpress.com", "a.aliexpress.com"),
    "pichau": ("pichau.com.br",),
    "terabyte": ("terabyteshop.com.br",),
    "casasbahia": ("casasbahia.com.br",),
    "americanas": ("americanas.com.br",),
    "carrefour": ("carrefour.com.br",),
    "netshoes": ("netshoes.com.br",),
}


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
    for slug, domains in STORES.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return slug
    return None


def main_link(links: Sequence[str]) -> str | None:
    for link in links:
        if store_of(link) is not None:
            return link
    return links[0] if links else None


_PRODUCT_LABELS = ("link produto", "link do produto")
_OTHER_LABELS = ("resgat", "carrinho")


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def product_link(text: str | None, links: Sequence[str]) -> str | None:
    """The link a post labels "Link produto", when it points at a known store.

    Shopee posts list the coupon page first ("Resgate todos os cupons desta página") and the
    real item second, so the first link alone would send the enricher to a coupon page.
    """
    if not text:
        return None
    waiting = False
    for line in text.splitlines():
        plain = _plain(line)
        if any(label in plain for label in _PRODUCT_LABELS):
            waiting = True
        elif any(label in plain for label in _OTHER_LABELS):
            waiting = False
        url = URL_PATTERN.search(line)
        if url is not None and waiting:
            raw = url.group(0)
            link = next((x for x in links if raw.startswith(x)), raw)
            return link if store_of(link) is not None else None
    return None
