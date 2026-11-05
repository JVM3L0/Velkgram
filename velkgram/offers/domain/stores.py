"""Store detection from link hosts (pure, no network)."""

from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit

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
