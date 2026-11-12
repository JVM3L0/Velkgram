"""Deal rules shared by alerting and offers: term matching and price extraction (pure)."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from velkgram.shared.text import URL_PATTERN


@dataclass(frozen=True, slots=True)
class WishView:
    id: int
    name: str
    required: tuple[tuple[str, ...], ...]  # AND of ORs, already normalized
    excluded: tuple[str, ...]  # already normalized
    max_price_cents: int
    user_id: int = 1  # owner of the wish: who receives its alerts


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


def within_over_max(price_cents: int, max_cents: int) -> bool:
    """True when the price is above the max but at most 1.5x of it (integer math, no floats)."""
    return max_cents < price_cents and price_cents * 2 <= max_cents * 3


def matches(wish: WishView, normalized_text: str, price_cents: int | None) -> bool:
    """Terms match and the price is unknown or within the wish's maximum."""
    if not matches_terms(wish, normalized_text):
        return False
    return price_cents is None or price_cents <= wish.max_price_cents


LOW_CAP_PCT = 5
"""A capped saving under this share of the price is flagged as low."""


@dataclass(frozen=True, slots=True)
class Saving:
    cents: int
    capped: bool
    low: bool


def min_not_met(min_cents: int | None, price_cents: int) -> bool:
    """True only when a minimum is set and the price is below it (equal counts as met)."""
    return min_cents is not None and min_cents > price_cents


_DISCOUNT_PERCENT = re.compile(r"(\d+)% OFF")
_DISCOUNT_CASH = re.compile(r"R\$ (\d+)(?:,(\d{2}))? OFF")


def coupon_saving(
    discount: str, min_cents: int | None, cap_cents: int | None, price_cents: int
) -> Saving | None:
    """What a coupon takes off `price_cents`; None if its minimum isn't met or it is unknown."""
    if min_not_met(min_cents, price_cents):
        return None
    cash = _DISCOUNT_CASH.fullmatch(discount)
    if cash is not None:
        value = int(cash.group(1)) * 100 + (int(cash.group(2)) if cash.group(2) else 0)
        return Saving(min(value, price_cents), capped=False, low=False)
    percent = _DISCOUNT_PERCENT.fullmatch(discount)
    if percent is None:
        return None
    cents = price_cents * int(percent.group(1)) // 100
    if cap_cents is None or cap_cents >= cents:
        return Saving(cents, capped=False, low=False)
    return Saving(cap_cents, capped=True, low=cap_cents * 100 < LOW_CAP_PCT * price_cents)


_COUPON_KEYWORD = re.compile(r"\b(?:cupom|cupons|cupon|c[óo]digo|code)\b", re.IGNORECASE)
_COUPON_TOKEN = re.compile(r"(?=[A-Z0-9_-]*[A-Z])[A-Z0-9_-]{3,25}")
_NOT_CODES = frozenset(
    {
        "OFF",
        "LIMITADO",
        "ATENÇÃO",
        "ATENCAO",
        "NOVO",
        "HOJE",
        "ACIMA",
        "FRETE",
        "GRATIS",
        "GRÁTIS",
        "PIX",
        "APP",
        "LINK",
        "AQUI",
        "SELECIONADAS",
        "SELECIONADOS",
    }
    | {  # store names from offers/domain/stores.py; shared cannot import a module
        "AMAZON",
        "MERCADOLIVRE",
        "MERCADO",
        "LIVRE",
        "SHOPEE",
        "MAGALU",
        "KABUM",
        "ALIEXPRESS",
        "PICHAU",
        "TERABYTE",
        "CASASBAHIA",
        "AMERICANAS",
        "CARREFOUR",
        "NETSHOES",
    }
)
_EDGE_PUNCTUATION = ".,;!?()[]\"'*"


def _as_code(raw: str) -> str | None:
    token = raw.strip(_EDGE_PUNCTUATION)
    if token in _NOT_CODES or _COUPON_TOKEN.fullmatch(token) is None:
        return None
    return token


def _starts_with_coupon_word(text: str) -> bool:
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    head = unicodedata.normalize("NFKD", first.lower())
    return "".join(c for c in head if unicodedata.category(c) != "Mn").startswith("cupom")


_COUPON_OFF = re.compile(r"\bOFF\b", re.IGNORECASE)
_ALTERNATIVES = re.compile(r"\s*(?:,|/|\+|\bou\b|\be\b)\s*", re.IGNORECASE)


def _codes_in(remainder: str) -> list[str]:
    """Codes joined by ",", "/", "+", "ou" or "e"; stops at the first piece that is not one."""
    codes: list[str] = []
    for piece in _ALTERNATIVES.split(remainder):
        words = piece.split()
        code = _as_code(words[0]) if words else None
        if code is None:
            break
        codes.append(code)
        if len(words) > 1:  # trailing prose: the list is over
            break
    return codes


def _line_codes(line: str, *, coupon_post: bool) -> list[str]:
    keyword = _COUPON_KEYWORD.search(line)
    if keyword is not None:
        anchor = keyword.end()
    else:
        # "Cupom Shopee" posts put codes on their own "R$ 10 OFF em R$ 40: CODE" lines.
        off = _COUPON_OFF.search(line) if coupon_post else None
        if off is None:
            return []
        anchor = off.end()
    colon = line.find(":", anchor)
    if colon != -1:
        return _codes_in(line[colon + 1 :])
    return _codes_in(line[anchor:]) if keyword is not None else []


def line_coupons(line: str) -> tuple[str, ...]:
    """Codes on one line of a coupon post, which may name them without the word "cupom"."""
    return tuple(dict.fromkeys(_line_codes(line, coupon_post=True)))


def extract_coupons(text: str) -> tuple[str, ...]:
    """Coupon codes in order of appearance, without duplicates (pure)."""
    coupon_post = _starts_with_coupon_word(text)
    found: dict[str, None] = {}
    for line in text.splitlines():
        for code in _line_codes(line, coupon_post=coupon_post):
            found[code] = None
    return tuple(found)


@dataclass(frozen=True, slots=True)
class ListItem:
    name: str
    price_cents: int
    link: str


@dataclass(frozen=True, slots=True)
class ProductList:
    header: str  # the post text before the first item: title, coupon notes, promo links
    items: tuple[ListItem, ...]


_NAME_EDGE = " -=:\u2013\u2022*"
_ITEM_LINK_LOOKAHEAD = 2


def _link_of(line: str, following: Sequence[str], links: Sequence[str]) -> str | None:
    """The link on the item's own line, else a bare URL line right after it."""
    url = URL_PATTERN.search(line)
    if url is None:
        candidates = [x.strip() for x in following if x.strip()][:_ITEM_LINK_LOOKAHEAD]
        url = next(
            (m for c in candidates if (m := URL_PATTERN.fullmatch(c)) is not None),
            None,
        )
    if url is None:
        return None
    raw = url.group(0)
    return next((x for x in links if raw.startswith(x)), raw)


def product_list(text: str, links: Sequence[str]) -> ProductList | None:
    """A post that lists several products, each with its own price and link, else None.

    Lines like "-NIVEA 150ml = R$ 87" followed by the product link. A single product that
    merely carries extra links (coupon page, "Link produto") is not a list.
    """
    lines = [line.strip() for line in text.splitlines()]
    items: list[ListItem] = []
    first: int | None = None
    for i, line in enumerate(lines):
        prices = listed_prices(line)
        if not prices:
            continue
        name = line.split("R$", 1)[0].strip(_NAME_EDGE)
        link = _link_of(line, lines[i + 1 :], links)
        if not name or link is None:
            continue
        if first is None:
            first = i
        items.append(ListItem(name, prices[0], link))
    if len(items) < 2 or first is None:
        return None
    return ProductList("\n".join(lines[:first]).strip(), tuple(items))
