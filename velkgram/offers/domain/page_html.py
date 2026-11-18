"""Title and image off a product page (regex over bounded slices; no parser dependency)."""

import re
from html import unescape

from velkgram.offers.domain.urls import is_safe_https_url

TITLE_MAX = 200
_IMAGE_MAX = 2000
_ATTR = re.compile(r'([\w:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')
_TAG_MAX = 4000
_MAX_METAS = 500
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")
_SPACES = re.compile(r"\s+")
_PRICE_SUFFIX = re.compile(r"\s+-\s+R\$\s*\d[\d.]*(?:,\d{1,2})?\s*$")


def meta_tags(body: str) -> dict[str, str]:
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


def html_title(body: str) -> str | None:
    start = body.find("<title")
    if start < 0:
        return None
    open_end = body.find(">", start)
    if open_end < 0:
        return None
    close = body.find("</title>", open_end, open_end + 1 + _TAG_MAX)
    return body[open_end + 1 : close] if close >= 0 else None


def clean_title(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = _SPACES.sub(" ", _CTRL.sub(" ", unescape(raw))).strip()
    return text[:TITLE_MAX].rstrip() or None


def clean_image(raw: str | None) -> str | None:
    if raw is None:
        return None
    url = unescape(raw).replace("\\/", "/").strip()
    if len(url) > _IMAGE_MAX or _CTRL.search(url) or not is_safe_https_url(url):
        return None
    return url


def og_page(body: str, *, strip_price: bool) -> tuple[str | None, str | None]:
    """Title and image from the Open Graph tags; `strip_price` drops a trailing " - R$ 99,90"."""
    metas = meta_tags(body)
    title = clean_title(metas.get("og:title"))
    if title and strip_price:
        title = clean_title(_PRICE_SUFFIX.sub("", title))
    return title, clean_image(metas.get("og:image"))
