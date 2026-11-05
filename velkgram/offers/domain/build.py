"""Build an Offer from a stored message (pure)."""

import hashlib
from datetime import datetime

from velkgram.offers.domain.comparable import is_comparable
from velkgram.offers.domain.coupon import coupon_deal, store_in_title
from velkgram.offers.domain.models import Offer, OfferKind
from velkgram.offers.domain.stores import main_link, store_of
from velkgram.offers.domain.title import title_of
from velkgram.shared.deals import WishView, extract_coupons, extract_price
from velkgram.shared.events import MessageData
from velkgram.shared.text import normalize_text


def offer_from_message(
    m: MessageData, *, sold_out: bool, deleted: bool, now: datetime
) -> Offer | None:
    text = m.text if m.text.strip() else None
    if text is None and not m.links:
        return None
    link = main_link(m.links)
    store = store_of(link) if link else None
    title = title_of(m.text, store)
    deal = coupon_deal(title, text, m.links)
    if deal is not None and store is None:
        store = store_in_title(title)  # short links (tidd.ly) hide the store; the title names it
    return Offer(
        channel_id=m.channel_id,
        message_id=m.message_id,
        posted_at=m.date,
        title=title,
        price_cents=None if deal else extract_price(m.text),
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
        comparable=is_comparable(title, text),
        kind=OfferKind.coupon if deal else OfferKind.product,
        coupons=extract_coupons(m.text),
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
