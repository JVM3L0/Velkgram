"""Price and image a store page states about its product (pure; never raises on bad input).

Pages that carry schema.org JSON-LD (KaBuM-style) are read here; a store whose page differs reads
it in its own module. A page that is unclear returns None: "unknown" is better than a wrong price.
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


def _as_dict(node: object) -> dict[str, object] | None:
    return cast("dict[str, object]", node) if isinstance(node, dict) else None


def _as_list(node: object) -> list[object]:
    return cast("list[object]", node) if isinstance(node, list) else [node]


def cents_of(value: object) -> int | None:
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
        if (cents := cents_of(raw)) is not None:
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
