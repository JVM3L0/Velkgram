"""Per-store link rules: what a followed link tells us about the product (pure)."""

import re
from dataclasses import dataclass
from html import unescape
from typing import Literal
from urllib.parse import unquote

from velkgram.offers.domain.stores import store_of
from velkgram.offers.domain.urls import host_of, is_safe_https_url

KB = 1024
TITLE_MAX = 200
_IMAGE_MAX = 2000

_SHORTENERS = frozenset({"cutt.ly", "tidd.ly", "bit.ly", "go.promotom.com.br", "link.amazon"})
_BUDGETS: dict[str, int] = {
    "amazon": 512 * KB,
    "mercadolivre": 512 * KB,
    "kabum": 16 * KB,
    "aliexpress": 0,
    "shopee": 0,
    "magalu": 0,
}
_DEFAULT_BUDGET = 64 * KB
_ALIEXPRESS_FIRST_HOP = "s.click.aliexpress.com"
_SHOPEE_SHORT = "s.shopee.com.br"
_MELI_SHORT = "meli.la"

Status = int | Literal["invalid", "error", "paused"]
Kind = Literal["product", "not_product", "unknown"]


@dataclass(frozen=True, slots=True)
class FetchPlan:
    follow: bool
    first_hop_only: bool
    # None: the budget is decided at the final hop through `budget_for`.
    body_budget: int | None


@dataclass(frozen=True, slots=True)
class FetchOutcome:
    final_url: str
    hops: tuple[str, ...]
    status: Status
    content_type: str | None
    body: str | None
    answered_by: str  # host that gave the final status


@dataclass(frozen=True, slots=True)
class LinkInfo:
    store: str | None
    product_id: str | None
    title: str | None
    image_url: str | None
    kind: Kind


_AMAZON_DIRECT = re.compile(r"/(?:dp|gp)/")


def _bare(host: str) -> str:
    return host.removeprefix("www.")


def fetch_plan(url: str) -> FetchPlan:
    host = _bare(host_of(url))
    if host == _ALIEXPRESS_FIRST_HOP:
        return FetchPlan(follow=False, first_hop_only=True, body_budget=0)
    if host == _SHOPEE_SHORT:
        return FetchPlan(follow=True, first_hop_only=False, body_budget=0)
    if host == _MELI_SHORT:
        return FetchPlan(follow=True, first_hop_only=False, body_budget=512 * KB)
    if host in _SHORTENERS:
        return FetchPlan(follow=True, first_hop_only=False, body_budget=None)
    if (host == "amazon.com.br" or host.endswith(".amazon.com.br")) and _AMAZON_DIRECT.search(
        _path(url)
    ):
        return FetchPlan(follow=False, first_hop_only=False, body_budget=512 * KB)
    return FetchPlan(follow=True, first_hop_only=False, body_budget=_DEFAULT_BUDGET)


def _path(url: str) -> str:
    return url.split("#", 1)[0].split("?", 1)[0]


def budget_for(url: str) -> int:
    """Body budget in bytes by the host of `url` (the final hop)."""
    return _BUDGETS.get(store_of(url) or "", _DEFAULT_BUDGET)


# --- product ids -----------------------------------------------------------------------

_ASIN = re.compile(r"/(?:dp|gp/product|gp/aw/d|gp/offer-listing)/([A-Za-z0-9]{10})(?![A-Za-z0-9])")
_MLB = re.compile(r"MLB-?(\d{6,})")
_SHOPEE_PATH = re.compile(r"/(\d+)/(\d+)(?:[/?#]|$)")
_SHOPEE_SLUG = re.compile(r"-i\.(\d+)\.(\d+)")
_MAGALU = re.compile(r"/p/(\d+)(?:[/?#]|$)")
_KABUM = re.compile(r"/produto/(\d+)")
_ALI_PRODUCT_ID = re.compile(r"productId=(\d{10,20})")
_ALI_ITEM = re.compile(r"/item/(\d{10,20})\.html")
_ITEM_ID = re.compile(r'"item_id"\s*:\s*"(MLB\d+)"')


def _id_in_url(store: str, url: str) -> str | None:
    if store == "amazon":
        m = _ASIN.search(_path(url))
        return m.group(1).upper() if m else None
    if store == "mercadolivre":
        m = _MLB.search(_path(url))
        return f"MLB{m.group(1)}" if m else None
    if store == "shopee":
        path = _path(url)
        m = _SHOPEE_SLUG.search(path)
        m = m or _SHOPEE_PATH.search(path)
        return f"{m.group(1)}.{m.group(2)}" if m else None
    if store == "magalu":
        m = _MAGALU.search(_path(url))
        return m.group(1) if m else None
    if store == "kabum":
        m = _KABUM.search(_path(url))
        return m.group(1) if m else None
    if store == "aliexpress":
        # The id sits in a (possibly url-encoded, nested) query string.
        text = url
        for _ in range(3):
            m = _ALI_PRODUCT_ID.search(text) or _ALI_ITEM.search(text)
            if m:
                return m.group(1)
            decoded = unquote(text)
            if decoded == text:
                break
            text = decoded
    return None


_ID_STORES = frozenset({"amazon", "mercadolivre", "shopee", "magalu", "kabum", "aliexpress"})


def resolve_url_only(url: str) -> LinkInfo | None:
    """Store and id from the URL alone, as a product with no title; None when unknown."""
    store = store_of(url)
    if store is None:
        return None
    product_id = _id_in_url(store, url)
    if product_id is None:
        return None
    return LinkInfo(store, product_id, None, None, "product")


# --- html reading (regex over bounded slices; no parser dependency) ---------------------

_ATTR = re.compile(r'([\w:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')
_TAG_MAX = 4000
_MAX_METAS = 500
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")
_SPACES = re.compile(r"\s+")


def _meta_tags(body: str) -> dict[str, str]:
    """First `content` per `og:*` / `name` / `property` key of the page's meta tags."""
    found: dict[str, str] = {}
    pos = 0
    for _ in range(_MAX_METAS):
        start = body.find("<meta", pos)
        if start < 0:
            break
        end = body.find(">", start)
        if end < 0:
            break
        pos = end + 1
        attrs: dict[str, str] = {}
        for m in _ATTR.finditer(body[start + 5 : min(end, start + _TAG_MAX)]):
            attrs[m.group(1).lower()] = m.group(2) if m.group(2) is not None else m.group(3)
        key = attrs.get("property") or attrs.get("name")
        content = attrs.get("content")
        if key and content is not None:
            found.setdefault(key.lower(), content)
    return found


def _html_title(body: str) -> str | None:
    start = body.find("<title")
    if start < 0:
        return None
    open_end = body.find(">", start)
    if open_end < 0:
        return None
    close = body.find("</title>", open_end, open_end + 1 + _TAG_MAX)
    return body[open_end + 1 : close] if close >= 0 else None


def _clean_title(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = _SPACES.sub(" ", _CTRL.sub(" ", unescape(raw))).strip()
    return text[:TITLE_MAX].rstrip() or None


def _clean_image(raw: str | None) -> str | None:
    if raw is None:
        return None
    url = unescape(raw).replace("\\/", "/").strip()
    if len(url) > _IMAGE_MAX or _CTRL.search(url) or not is_safe_https_url(url):
        return None
    return url


_PRICE_SUFFIX = re.compile(r"\s+-\s+R\$\s*\d[\d.]*(?:,\d{1,2})?\s*$")
_AMAZON_PREFIX = re.compile(r"^\s*Amazon\.com\.br\s*:\s*", re.IGNORECASE)
_AMAZON_SUFFIX = re.compile(r"\s*:\s*Amazon\.com\.br.*$", re.IGNORECASE | re.DOTALL)
_HIRES = re.compile(r'"hiRes"\s*:\s*"(https:[^"]{1,2000})"')
_OLD_HIRES = re.compile(r'data-old-hires="(https:[^"]{1,2000})"')


def _is_amazon_blocked(body: str) -> bool:
    lowered = body.lower()
    title = (_html_title(lowered) or "").strip()
    return "robot check" in title or "captcha" in title or "/errors/validatecaptcha" in lowered


def _amazon_page(body: str) -> tuple[str | None, str | None]:
    metas = _meta_tags(body)
    raw = metas.get("title") or _html_title(body)
    if raw is not None:
        raw = _AMAZON_SUFFIX.sub("", _AMAZON_PREFIX.sub("", unescape(raw)))
    m = _HIRES.search(body) or _OLD_HIRES.search(body)
    return _clean_title(raw), _clean_image(m.group(1) if m else None)


def _og_page(body: str, *, strip_price: bool) -> tuple[str | None, str | None]:
    metas = _meta_tags(body)
    raw = metas.get("og:title")
    title = _clean_title(raw)
    if title and strip_price:
        title = _clean_title(_PRICE_SUFFIX.sub("", title))
    return title, _clean_image(metas.get("og:image"))


def resolve(original_url: str, outcome: FetchOutcome) -> LinkInfo:
    """What a fetch outcome says about the link (spec §5.3). Never raises on bad input."""
    candidates = (outcome.final_url, *outcome.hops, original_url)
    store = next((s for url in candidates if (s := store_of(url))), None)
    product_id = None
    if store in _ID_STORES:
        product_id = next((i for url in candidates if (i := _id_in_url(store, url))), None)

    body = outcome.body
    read_ok = isinstance(outcome.status, int) and outcome.status < 400
    if body is not None and not read_ok:
        body = None

    if store == "amazon" and body is not None and _is_amazon_blocked(body):
        return LinkInfo(store, product_id, None, None, "unknown")

    if product_id is None and store == "mercadolivre" and body is not None:
        m = _ITEM_ID.search(body)
        product_id = m.group(1) if m else None

    if product_id is not None:
        title, image = _page_details(store, body)
        return LinkInfo(store, product_id, title, image, "product")

    if store in _ID_STORES:
        return LinkInfo(store, None, None, None, "not_product" if read_ok else "unknown")

    final_host = _bare(host_of(outcome.final_url))
    if body is None or final_host in _SHORTENERS:
        return LinkInfo(store, None, None, None, "unknown")
    title, image = _og_page(body, strip_price=False)
    return LinkInfo(store, None, title, image, "unknown")


def _page_details(store: str | None, body: str | None) -> tuple[str | None, str | None]:
    if body is None:
        return None, None
    if store == "amazon":
        return _amazon_page(body)
    return _og_page(body, strip_price=store == "mercadolivre")
