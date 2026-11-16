"""Price and image a store page states about its product (pure; never raises on bad input).

KaBuM-style pages carry schema.org JSON-LD; Amazon only has the price in its price block. A page
that is unclear returns None: "unknown" is better than a wrong price.
"""

import json
import re
from decimal import Decimal, InvalidOperation
from typing import cast

_LD_JSON = re.compile(
    r"<script[^>]+type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_MAX_BLOCKS = 10
_MAX_DEPTH = 8
_MAX_CENTS = 100_000_000_00  # R$ 100 million: anything above is a parsing accident
_PRODUCT_TYPES = {"product", "productgroup"}
_BRL = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})")
_AMAZON_PRICE_BLOCKS = ("corePriceDisplay_desktop_feature_div", "corePrice_feature_div")
_OFFSCREEN = re.compile(r'class="a-offscreen">([^<]{1,40})<')
_BLOCK_WINDOW = 4000


def _as_dict(node: object) -> dict[str, object] | None:
    return cast("dict[str, object]", node) if isinstance(node, dict) else None


def _as_list(node: object) -> list[object]:
    return cast("list[object]", node) if isinstance(node, list) else [node]


def _cents(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        cents = int(Decimal(str(value).strip()) * 100)
    except InvalidOperation:
        return None
    return cents if 0 < cents <= _MAX_CENTS else None


def _types(node: dict[str, object]) -> set[str]:
    return {str(t).lower() for t in _as_list(node.get("@type"))}


def _products(node: object, depth: int = 0) -> list[dict[str, object]]:
    if depth > _MAX_DEPTH:
        return []
    if isinstance(node, list):
        return [p for item in _as_list(cast("object", node)) for p in _products(item, depth + 1)]
    data = _as_dict(node)
    if data is None:
        return []
    found = [data] if _types(data) & _PRODUCT_TYPES else []
    for key in ("@graph", "mainEntity"):
        found.extend(_products(data.get(key), depth + 1))
    return found


def _offer_price(offers: object) -> int | None:
    """The single price of a product's offers; None when the offers disagree."""
    prices: set[int] = set()
    for item in _as_list(offers):
        offer = _as_dict(item)
        if offer is None:
            continue
        spec = _as_dict(offer.get("priceSpecification"))
        raw = offer.get("price")
        if raw is None and spec is not None:
            raw = spec.get("price")
        if raw is None:
            raw = offer.get("lowPrice")
        if (cents := _cents(raw)) is not None:
            prices.add(cents)
    return next(iter(prices)) if len(prices) == 1 else None


def _first_image(raw: object) -> str | None:
    if isinstance(raw, list):
        return next((i for x in _as_list(cast("object", raw)) if (i := _first_image(x))), None)
    data = _as_dict(raw)
    if data is not None:
        return _first_image(data.get("url"))
    return raw if isinstance(raw, str) and raw.strip() else None


def _jsonld_products(body: str) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for raw in _LD_JSON.findall(body)[:_MAX_BLOCKS]:
        try:
            found.extend(_products(json.loads(raw)))
        except ValueError:
            continue
    return found


def jsonld_price(body: str) -> int | None:
    """The product's price in cents from schema.org JSON-LD; None if absent or ambiguous."""
    prices = {p for node in _jsonld_products(body) if (p := _offer_price(node.get("offers")))}
    return next(iter(prices)) if len(prices) == 1 else None


def jsonld_image(body: str) -> str | None:
    return next(
        (i for node in _jsonld_products(body) if (i := _first_image(node.get("image")))), None
    )


def amazon_price(body: str) -> int | None:
    """The main price shown in Amazon's price block; None when the block or its price is unclear."""
    for marker in _AMAZON_PRICE_BLOCKS:
        start = body.find(marker)
        if start < 0:
            continue
        window = body[start : start + _BLOCK_WINDOW]
        # The first one is the price; later ones are per-unit or list prices.
        first = next(
            (
                _cents(m.group(1).replace(".", "").replace(",", "."))
                for text in _OFFSCREEN.findall(window)
                if (m := _BRL.search(text.replace("\xa0", " ")))
            ),
            None,
        )
        return first
    return None


def page_price(store: str | None, body: str | None) -> int | None:
    if body is None:
        return None
    if store == "amazon":
        return amazon_price(body)
    return jsonld_price(body)
