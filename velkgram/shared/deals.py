"""Deal rules shared by alerting and offers: term matching and price extraction (pure)."""

import re
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class WishView:
    id: int
    name: str
    required: tuple[tuple[str, ...], ...]  # AND of ORs, already normalized
    excluded: tuple[str, ...]  # already normalized
    max_price_cents: int


@lru_cache(maxsize=4096)
def _pattern(alternative: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(alternative)}(?!\w)")


def _found(alternative: str, text: str) -> bool:
    return _pattern(alternative).search(text) is not None


def matches_terms(wish: WishView, normalized_text: str) -> bool:
    if not all(any(_found(alt, normalized_text) for alt in group) for group in wish.required):
        return False
    return not any(_found(alt, normalized_text) for alt in wish.excluded)


_NUM = r"(?P<num>\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+(?:,\d{2})?)(?!\d|[.,]\d|\s*x\b)"
_VALUE = re.compile(
    rf"(?:R\$\s*|\b(?:por|só|apenas)\s+){_NUM}",
    re.IGNORECASE,
)
_INSTALLMENT_BEFORE = re.compile(r"\d+\s*x\s*(?:de\s*)?$", re.IGNORECASE)
_INSTALLMENT_AFTER = re.compile(r"\s*/\s*m[eê]s|\s+sem\s+juros", re.IGNORECASE)
_OLD_BEFORE = re.compile(r"\bde\s*$", re.IGNORECASE)
_OLD_AFTER = re.compile(r"\s+por\b", re.IGNORECASE)
_WINDOW = 24


def _to_cents(num: str) -> int:
    whole, _, frac = num.replace(".", "").partition(",")
    return int(whole) * 100 + (int(frac) if frac else 0)


_REAIS = re.compile(rf"R\$\s*{_NUM}", re.IGNORECASE)


def listed_prices(text: str) -> list[int]:
    """Every `R$` value in cents, minus installments and the old price of a "de X por Y" pair."""
    found: list[int] = []
    for match in _REAIS.finditer(text):
        before = text[max(0, match.start() - _WINDOW) : match.start()]
        after = text[match.end() : match.end() + _WINDOW]
        if _INSTALLMENT_BEFORE.search(before) or _INSTALLMENT_AFTER.match(after):
            continue
        if _OLD_BEFORE.search(before) and _OLD_AFTER.match(after):
            continue
        found.append(_to_cents(match.group("num")))
    return found


def extract_price(text: str) -> int | None:
    """Return the deal price in cents (BRL), or None when unknown."""
    for match in _VALUE.finditer(text):
        before = text[max(0, match.start() - _WINDOW) : match.start()]
        after = text[match.end() : match.end() + _WINDOW]
        if _INSTALLMENT_BEFORE.search(before) or _INSTALLMENT_AFTER.match(after):
            continue
        if _OLD_BEFORE.search(before) and _OLD_AFTER.match(after):
            continue
        return _to_cents(match.group("num"))
    return None


def matches(wish: WishView, normalized_text: str, price_cents: int | None) -> bool:
    """Terms match and the price is unknown or within the wish's maximum."""
    if not matches_terms(wish, normalized_text):
        return False
    return price_cents is None or price_cents <= wish.max_price_cents
