import sqlite3
from datetime import UTC, datetime, timedelta

from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository
from velkgram.offers.domain.models import CouponTier, MatchSource, Offer, OfferKind, OfferMatch

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def offer(
    message_id: int,
    *,
    channel_id: int = 1,
    at: datetime | None = None,
    title: str = "SSD Kingston 1TB",
    price: int | None = 29990,
    store: str | None = "amazon",
    text: str | None = "SSD Kingston 1TB por R$ 299,90",
    origin: tuple[int, int] | None = None,
    sold_out: bool = False,
    deleted: bool = False,
    comparable: bool = True,
    coupon: tuple[str, ...] = (),
    kind: OfferKind = OfferKind.product,
    coupon_tiers: tuple[CouponTier, ...] | None = None,
    coupon_discount: str | None = None,
    link: str | None = "https://x.test/p",
) -> Offer:
    when = at or T0 + timedelta(minutes=message_id)
    return Offer(
        channel_id=channel_id,
        message_id=message_id,
        posted_at=when,
        title=title,
        price_cents=price,
        store=store,
        main_link=link,
        has_photo=False,
        text=text,
        norm_text=text.lower() if text else None,
        origin_channel_id=origin[0] if origin else None,
        origin_message_id=origin[1] if origin else None,
        sold_out=sold_out,
        deleted=deleted,
        updated_at=when,
        comparable=comparable,
        kind=kind,
        coupons=coupon,
        coupon_discount=coupon_discount or ("R$ 10 OFF" if kind is OfferKind.coupon else None),
        coupon_min_cents=4000 if kind is OfferKind.coupon else None,
        redeem_link="https://x.test/resgate" if kind is OfferKind.coupon else None,
        coupon_tiers=(
            coupon_tiers
            if coupon_tiers is not None
            else ((CouponTier("R$ 10 OFF", 4000),) if kind is OfferKind.coupon else ())
        ),
    )


def put(conn: sqlite3.Connection, *offers: Offer) -> None:
    repo = SqliteOfferRepository(conn)
    for o in offers:
        repo.upsert(o)


def match(
    wish_id: int, o: Offer, source: MatchSource = MatchSource.live, price: int | None = -1
) -> OfferMatch:
    return OfferMatch(
        wish_id=wish_id,
        channel_id=o.channel_id,
        message_id=o.message_id,
        price_cents=o.price_cents if price == -1 else price,
        posted_at=o.posted_at,
        source=source,
        matched_at=o.posted_at,
    )


def add_link(
    conn: sqlite3.Connection,
    url: str,
    *,
    store: str | None = "amazon",
    product_id: str | None = None,
    image_url: str | None = None,
    kind: str = "product",
) -> None:
    """Insert an enriched product_links row directly (the enricher is not under test here)."""
    stamp = T0.isoformat()
    with conn:
        conn.execute(
            "INSERT INTO product_links (url, store, product_id, image_url, kind, status, "
            "created_at, offer_posted_at, host) VALUES (?,?,?,?,?,'done',?,?,'x.test')",
            (url, store, product_id, image_url, kind, stamp, stamp),
        )
