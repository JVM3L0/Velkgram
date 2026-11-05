"""Coupon posts ("Cupom Shopee R$ 10 OFF em R$ 40: CODE"): what they offer and where to use them."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from velkgram.shared.text import URL_PATTERN

_MONEY = r"R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{2}))?"
_DISCOUNT = re.compile(rf"(?:{_MONEY}|(\d+)\s*%)\s*OFF\b", re.IGNORECASE)
_MIN_SPEND = re.compile(rf"\b(?:em|acima\s+de|a\s+partir\s+de)\s+{_MONEY}", re.IGNORECASE)
_SCOPE = re.compile(r"\bOFF\s+em\s+(?!R\$)([^:\n,;-]+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CouponDeal:
    discount: str
    min_cents: int | None
    scope: str | None
    redeem_link: str | None
    cart_link: str | None


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def starts_with_coupon_word(title: str) -> bool:
    return _plain(title).startswith("cupom")


def _cents(reais: str, cents: str | None) -> int:
    return int(reais.replace(".", "")) * 100 + (int(cents) if cents else 0)


def _discount(text: str) -> str:
    match = _DISCOUNT.search(text)
    if match is None:
        return ""
    if match.group(3) is not None:
        return f"{match.group(3)}% OFF"
    return (
        f"R$ {match.group(1).replace('.', '')} OFF"
        if match.group(2) is None
        else (f"R$ {match.group(1).replace('.', '')},{match.group(2)} OFF")
    )


def _links_after_keywords(text: str, links: Sequence[str]) -> tuple[str | None, str | None]:
    """The first link after a "resgat…" line and the first after a "…carrinho" line."""
    found: dict[str, str] = {}
    waiting: str | None = None
    for line in text.splitlines():
        plain = _plain(line)
        if "resgat" in plain:
            waiting = "redeem"
        elif "carrinho" in plain:
            waiting = "cart"
        url = URL_PATTERN.search(line)
        if url is not None and waiting is not None:
            raw = url.group(0)
            found.setdefault(waiting, next((x for x in links if raw.startswith(x)), raw))
            waiting = None
    return found.get("redeem"), found.get("cart")


def coupon_deal(title: str, text: str | None, links: Sequence[str]) -> CouponDeal | None:
    if not starts_with_coupon_word(title):
        return None
    if text is None:
        return CouponDeal("", None, None, None, None)
    minimum = _MIN_SPEND.search(text)
    scope = _SCOPE.search(text)
    redeem, cart = _links_after_keywords(text, links)
    return CouponDeal(
        discount=_discount(text),
        min_cents=_cents(minimum.group(1), minimum.group(2)) if minimum else None,
        scope=scope.group(1).strip() if scope else None,
        redeem_link=redeem,
        cart_link=cart,
    )
