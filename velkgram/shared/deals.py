"""Deal rules shared by alerting and offers: term matching and price extraction (pure)."""

import re
import unicodedata
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
