"""Brazilian deal-post price extraction (pure, regex only)."""

import re

_NUM = r"(?P<num>\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+(?:,\d{2})?)(?!\d)"
_VALUE = re.compile(
    rf"(?:R\$\s*|\b(?:por|só|apenas)\s+){_NUM}",
    re.IGNORECASE,
)
_INSTALLMENT_BEFORE = re.compile(r"\d+\s*x\s*de\s*$", re.IGNORECASE)
_INSTALLMENT_AFTER = re.compile(r"\s*/\s*m[eê]s|\s+sem\s+juros", re.IGNORECASE)
_OLD_BEFORE = re.compile(r"\bde\s*$", re.IGNORECASE)
_OLD_AFTER = re.compile(r"\s+por\b", re.IGNORECASE)
_WINDOW = 24


def _to_cents(num: str) -> int:
    whole, _, frac = num.replace(".", "").partition(",")
    return int(whole) * 100 + (int(frac) if frac else 0)


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
