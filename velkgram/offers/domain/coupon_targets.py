"""Which wishlist offers a coupon post can apply to (pure)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from velkgram.offers.domain.models import CouponTier, Offer, OfferKind
from velkgram.shared.deals import (
    WishView,
    coupon_saving,
    matches_terms,
    min_not_met,
    within_over_max,
)
from velkgram.shared.events import CouponTargetData

_LOOKBACK = timedelta(days=3)


@dataclass(frozen=True, slots=True)
class AppliedTier:
    discount: str
    min_cents: int | None
    codes: tuple[str, ...]
    cap_cents: int | None = None


def applicable_tier(
    tiers: Sequence[CouponTier],
    min_cents: int | None,
    discount: str,
    codes: tuple[str, ...],
    price_cents: int,
) -> AppliedTier | None:
    """The tier saving the most at the price (ties: highest minimum, then first), else None."""
    if not tiers:
        tiers = (CouponTier(discount, min_cents, None, codes),)
    best: CouponTier | None = None
    best_key = (-1, -1)
    for tier in tiers:
        if min_not_met(tier.min_cents, price_cents):
            continue
        saving = coupon_saving(tier.discount, tier.min_cents, tier.cap_cents, price_cents)
        key = (saving.cents if saving else 0, tier.min_cents or 0)
        if key > best_key:
            best, best_key = tier, key
    if best is None:
        return None
    return AppliedTier(best.discount, best.min_cents, best.codes or codes, best.cap_cents)


def _is_candidate(offer: Offer, coupon: Offer, now: datetime) -> bool:
    return (
        offer.kind == OfferKind.product
        and offer.store == coupon.store
        and offer.price_cents is not None
        and not offer.deleted
        and not offer.sold_out
        and offer.norm_text is not None
        and coupon.posted_at - _LOOKBACK <= offer.posted_at <= now
    )


def coupon_targets(
    coupon: Offer, wishes: Sequence[WishView], offers: Sequence[Offer], now: datetime
) -> tuple[CouponTargetData, ...]:
    if (
        coupon.kind != OfferKind.coupon
        or coupon.store is None
        or not coupon.coupons
        or coupon.deleted
        or coupon.sold_out
    ):
        return ()
    candidates = [o for o in offers if _is_candidate(o, coupon, now)]
    targets: list[CouponTargetData] = []
    for wish in wishes:
        best: tuple[Offer, AppliedTier] | None = None
        for offer in candidates:
            price = offer.price_cents
            assert price is not None and offer.norm_text is not None
            if not matches_terms(wish, offer.norm_text):
                continue
            if price > wish.max_price_cents and not within_over_max(price, wish.max_price_cents):
                continue
            tier = applicable_tier(
                coupon.coupon_tiers,
                coupon.coupon_min_cents,
                coupon.coupon_discount or "",
                coupon.coupons,
                price,
            )
            if tier is None:
                continue
            if best is None or _better(offer, best[0]):
                best = (offer, tier)
        if best is not None:
            offer, tier = best
            assert offer.price_cents is not None
            targets.append(
                CouponTargetData(
                    wish_id=wish.id,
                    offer_channel_id=offer.channel_id,
                    offer_message_id=offer.message_id,
                    offer_price_cents=offer.price_cents,
                    over_max=offer.price_cents > wish.max_price_cents,
                    discount=tier.discount,
                    min_cents=tier.min_cents,
                    codes=tier.codes,
                    cap_cents=tier.cap_cents,
                )
            )
    return tuple(targets)


def _better(a: Offer, b: Offer) -> bool:
    """Cheaper wins; among equal prices the newest."""
    assert a.price_cents is not None and b.price_cents is not None
    return (a.price_cents, -a.posted_at.timestamp()) < (b.price_cents, -b.posted_at.timestamp())
