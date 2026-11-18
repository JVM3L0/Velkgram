"""Amazon: ASIN ids, direct /dp/ links read as they are, an anti-bot wall and its own price."""

import re
from dataclasses import dataclass
from html import unescape

from velkgram.offers.domain.link_types import KB, FetchPlan
from velkgram.offers.domain.page_html import clean_image, clean_title, html_title, meta_tags
from velkgram.offers.domain.page_price import cents_of
from velkgram.offers.domain.stores.base import BaseStore, short_host_plan
from velkgram.offers.domain.urls import strip_query

_DIRECT = re.compile(r"/(?:dp|gp)/")
_ASIN = re.compile(r"/(?:dp|gp/product|gp/aw/d|gp/offer-listing)/([A-Za-z0-9]{10})(?![A-Za-z0-9])")
_PREFIX = re.compile(r"^\s*Amazon\.com\.br\s*:\s*", re.IGNORECASE)
_SUFFIX = re.compile(r"\s*:\s*Amazon\.com\.br.*$", re.IGNORECASE | re.DOTALL)
_HIRES = re.compile(r'"hiRes"\s*:\s*"(https:[^"]{1,2000})"')
_OLD_HIRES = re.compile(r'data-old-hires="(https:[^"]{1,2000})"')
_PRICE_BLOCKS = ("corePriceDisplay_desktop_feature_div", "corePrice_feature_div")
_OFFSCREEN = re.compile(r'class="a-offscreen">([^<]{1,40})<')
_BRL = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})")
_BLOCK_WINDOW = 4000
_BUDGET = 512 * KB


def amazon_price(body: str) -> int | None:
    """The main price shown in Amazon's price block; None when the block or its price is unclear."""
    for marker in _PRICE_BLOCKS:
        start = body.find(marker)
        if start < 0:
            continue
        window = body[start : start + _BLOCK_WINDOW]
        # The first one is the price; later ones are per-unit or list prices.
        first = next(
            (
                cents_of(m.group(1).replace(".", "").replace(",", "."))
                for text in _OFFSCREEN.findall(window)
                if (m := _BRL.search(text.replace("\xa0", " ")))
            ),
            None,
        )
        return first
    return None


@dataclass(frozen=True, slots=True)
class Amazon(BaseStore):
    def fetch_plan(self, url: str, host: str) -> FetchPlan | None:
        direct = host == "amazon.com.br" or host.endswith(".amazon.com.br")
        if direct and _DIRECT.search(strip_query(url)):
            return FetchPlan(follow=False, first_hop_only=False, body_budget=_BUDGET)
        return short_host_plan(self, host)

    def product_id_in_url(self, url: str) -> str | None:
        m = _ASIN.search(strip_query(url))
        return m.group(1).upper() if m else None

    def is_blocked(self, body: str) -> bool:
        lowered = body.lower()
        title = (html_title(lowered) or "").strip()
        return (
            "robot check" in title
            or "captcha" in title
            or 'action="/errors/validatecaptcha' in lowered
        )

    def page_details(self, body: str) -> tuple[str | None, str | None]:
        raw = meta_tags(body).get("title") or html_title(body)
        if raw is not None:
            raw = _SUFFIX.sub("", _PREFIX.sub("", unescape(raw)))
        m = _HIRES.search(body) or _OLD_HIRES.search(body)
        return clean_title(raw), clean_image(m.group(1) if m else None)

    def page_price(self, body: str) -> int | None:
        return amazon_price(body)

    def product_url(self, product_id: str) -> str | None:
        return f"https://www.amazon.com.br/dp/{product_id}"


AMAZON = Amazon(
    slug="amazon",
    name="Amazon",
    domains=("amazon.com.br", "amzn.to", "amzn.divulgador.link", "link.amazon"),
    body_budget=_BUDGET,
    short_hosts=frozenset({"link.amazon", "amzn.to", "amzn.divulgador.link"}),
    identifies_products=True,
)
