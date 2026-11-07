"""URL helpers shared by the link rules and the web views (pure)."""

from urllib.parse import urlsplit


def strip_query(url: str) -> str:
    """The URL without its query string and fragment (affiliate tokens live there)."""
    return url.split("#", 1)[0].split("?", 1)[0]


def _scheme(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urlsplit(url).scheme.lower()
    except ValueError:  # e.g. "http://[::1": a garbled link must not break callers
        return ""


def is_safe_url(url: str | None) -> bool:
    """True only for http and https (never javascript:, tg:, data:)."""
    return _scheme(url) in ("http", "https")


def is_safe_https_url(url: str | None) -> bool:
    return _scheme(url) == "https"


def host_of(url: str) -> str:
    """Lowercase host of `url`, or "" when there is none."""
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def product_url(store: str | None, product_id: str | None) -> str | None:
    """The canonical product page of a store item, or None when the store has no stable one."""
    if not store or not product_id:
        return None
    if store == "amazon":
        return f"https://www.amazon.com.br/dp/{product_id}"
    if store == "mercadolivre":
        return f"https://www.mercadolivre.com.br/p/{product_id}"
    if store == "kabum":
        return f"https://www.kabum.com.br/produto/{product_id}"
    if store == "shopee":
        shop, _, item = product_id.partition(".")
        return f"https://shopee.com.br/product/{shop}/{item}" if shop and item else None
    if store == "aliexpress":
        return f"https://pt.aliexpress.com/item/{product_id}.html"
    return None


def real_product_url(
    store: str | None, product_id: str | None, kind: str | None, final_url: str | None
) -> str | None:
    """The real product link of an enriched offer: built from the id, else the resolved URL."""
    if kind != "product":
        return None
    url = product_url(store, product_id) or final_url
    return url if is_safe_https_url(url) else None
