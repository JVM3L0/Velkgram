"""Reading a deal post's links: the main one and the one it labels as the product (pure)."""

import unicodedata
from collections.abc import Sequence

from velkgram.offers.domain.stores.registry import store_of
from velkgram.shared.text import URL_PATTERN


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
