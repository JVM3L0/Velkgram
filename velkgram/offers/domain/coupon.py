"""Coupon posts ("Cupom Shopee R$ 10 OFF em R$ 40: CODE"): what they offer and where to use them."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from velkgram.offers.domain.models import CouponTier
from velkgram.offers.domain.title import STORE_TITLES
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
    tiers: tuple[CouponTier, ...] = ()


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def starts_with_coupon_word(title: str) -> bool:
    return _plain(title).startswith("cupom")


def _store_words(slug: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", _plain(STORE_TITLES[slug]))


def store_in_title(title: str) -> str | None:
    """The store named as a whole word in a coupon title ("Cupom KaBuM ..."), else None."""
    plain = re.sub(r"[^a-z0-9 ]", " ", _plain(title))
    for slug in STORE_TITLES:
        for name in {slug, _store_words(slug)}:
            if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", plain):
                return slug
    return None


def _cents(reais: str, cents: str | None) -> int:
    return int(reais.replace(".", "")) * 100 + (int(cents) if cents else 0)


def _discount_text(match: re.Match[str]) -> str:
    if match.group(3) is not None:
        return f"{match.group(3)}% OFF"
    reais = match.group(1).replace(".", "")
    return f"R$ {reais} OFF" if match.group(2) is None else f"R$ {reais},{match.group(2)} OFF"


def _tiers(text: str) -> tuple[CouponTier, ...]:
    tiers: list[CouponTier] = []
    for line in text.splitlines():
        discount = _DISCOUNT.search(line)
        if discount is None:
            continue
        minimum = _MIN_SPEND.search(line)
        tiers.append(
            CouponTier(
                _discount_text(discount),
                _cents(minimum.group(1), minimum.group(2)) if minimum else None,
            )
        )
    return tuple(tiers)


def _tier_value(tier: CouponTier) -> int:
    number = re.search(r"\d[\d.]*(?:,\d+)?", tier.discount)
    return int(float(number.group(0).replace(".", "").replace(",", ".")) * 100) if number else 0


def best_tier(tiers: Sequence[CouponTier]) -> CouponTier | None:
    """The headline tier: the biggest cash discount, else the biggest percentage."""
    cash = [t for t in tiers if t.discount.startswith("R$")]
    pool = cash or list(tiers)
    return max(pool, key=_tier_value, default=None)


_LEADING_CUPOM = re.compile(r"^cupom(?:ns)?\b[\s:,-]*", re.IGNORECASE)
_EDGE_NOISE = " \t-–—:,;"


def coupon_title(title: str) -> str:
    """The title without what the card already shows: discount phrases and "Cupom <Store>"."""
    rest = " ".join(_DISCOUNT.sub(" ", title).split()).strip(_EDGE_NOISE)
    rest = _LEADING_CUPOM.sub("", rest)
    for slug in STORE_TITLES:
        for name in sorted({slug, STORE_TITLES[slug]}, key=len, reverse=True):
            if _plain(rest[: len(name)]) == _plain(name) and (
                len(rest) == len(name) or not rest[len(name)].isalnum()
            ):
                return rest[len(name) :].strip(_EDGE_NOISE)
    return rest.strip(_EDGE_NOISE)


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
    tiers = _tiers(text)
    first = tiers[0] if tiers else CouponTier("", None)
    minimum = _MIN_SPEND.search(text) if len(tiers) <= 1 else None
    min_cents = first.min_cents
    if min_cents is None and minimum:
        min_cents = _cents(minimum.group(1), minimum.group(2))
    scope = _SCOPE.search(text)
    redeem, cart = _links_after_keywords(text, links)
    return CouponDeal(
        discount=first.discount,
        min_cents=min_cents,
        scope=scope.group(1).strip() if scope else None,
        redeem_link=redeem,
        cart_link=cart,
        tiers=tiers,
    )
