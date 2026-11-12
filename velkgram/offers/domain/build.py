"""Build an Offer from a stored message (pure)."""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from velkgram.offers.domain.comparable import is_comparable
from velkgram.offers.domain.coupon import CouponDeal, coupon_deal, store_in_title
from velkgram.offers.domain.models import Offer, OfferKind
from velkgram.offers.domain.stores import main_link, product_link, store_of
from velkgram.offers.domain.title import title_of
from velkgram.shared.deals import WishView, extract_coupons, extract_price, product_list
from velkgram.shared.events import MessageData
from velkgram.shared.text import normalize_text


@dataclass(frozen=True, slots=True)
class MessageClass:
    store: str | None
    is_coupon_post: bool


def _classify(m: MessageData) -> tuple[str | None, str | None, str, CouponDeal | None, bool]:
    link = product_link(m.text, m.links) or main_link(m.links)
    store = store_of(link) if link else None
    title = title_of(m.text, store)
    text = m.text if m.text.strip() else None
    deal = coupon_deal(title, text, m.links, m.has_photo)
    if deal is not None and store is None:
        store = store_in_title(title)  # short links (tidd.ly) hide the store; the title names it
    # A list of products has no single price or product link: the first link is a promo page.
    listing = deal is None and product_list(m.text, m.links) is not None
    if listing:
        link = None
        store = next((s for x in m.links if (s := store_of(x))), None)
    return link, store, title, deal, listing


def _codes(text: str, deal: CouponDeal | None) -> tuple[str, ...]:
    """Codes named in the post; a coupon recognised by its shape also reads them from its tiers."""
    codes = extract_coupons(text)
    if codes or deal is None:
        return codes
    return tuple(dict.fromkeys(c for tier in deal.tiers for c in tier.codes))


def classify_message(m: MessageData) -> MessageClass:
    """Store and coupon-post flag of a message; `offer_from_message` shares this logic."""
    _, store, _, deal, _ = _classify(m)
    return MessageClass(store=store, is_coupon_post=deal is not None)


def _kind(
    deal: CouponDeal | None, price: int | None, link: str | None, store: str | None, m: MessageData
) -> OfferKind:
    """Coupon, channel chatter, or a product.

    Chatter ("Precin", "Última chance!", "Menor preço histórico?") has no price, no link, no store
    and no photo: nothing to buy or open. It stays stored but is never shown as an offer.
    """
    if deal is not None:
        return OfferKind.coupon
    if price is None and link is None and store is None and not m.links and not m.has_photo:
        return OfferKind.chatter
    return OfferKind.product


def offer_from_message(
    m: MessageData, *, sold_out: bool, deleted: bool, now: datetime
) -> Offer | None:
    text = m.text if m.text.strip() else None
    if text is None and not m.links:
        return None
    link, store, title, deal, listing = _classify(m)
    price = None if deal or listing else extract_price(m.text)
    kind = _kind(deal, price, link, store, m)
    return Offer(
        channel_id=m.channel_id,
        message_id=m.message_id,
        posted_at=m.date,
        title=title,
        price_cents=price,
        store=store,
        main_link=link,
        has_photo=m.has_photo,
        text=text,
        norm_text=normalize_text(text) if text is not None else None,
        origin_channel_id=m.fwd_from_channel_id,
        origin_message_id=m.fwd_from_message_id,
        sold_out=sold_out,
        deleted=deleted,
        updated_at=now,
        comparable=False if deal or kind is OfferKind.chatter else is_comparable(title, text),
        kind=kind,
        coupons=_codes(m.text, deal),
        coupon_discount=(deal.discount or None) if deal else None,
        coupon_min_cents=deal.min_cents if deal else None,
        coupon_scope=deal.scope if deal else None,
        redeem_link=deal.redeem_link if deal else None,
        cart_link=deal.cart_link if deal else None,
        coupon_tiers=deal.tiers if deal else (),
    )


def wish_fingerprint(w: WishView) -> str:
    key = repr((w.required, w.excluded, w.max_price_cents))
    return hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()
