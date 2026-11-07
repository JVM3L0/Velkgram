from dataclasses import replace
from datetime import UTC, datetime, timedelta

from tests.offers.domain.test_coupon import KABUM, MERCADO_LIVRE, SHOPEE
from velkgram.offers.domain.build import offer_from_message
from velkgram.offers.domain.coupon_targets import AppliedTier, applicable_tier, coupon_targets
from velkgram.offers.domain.models import CouponTier, Offer
from velkgram.shared.deals import WishView
from velkgram.shared.events import MessageData

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
COUPON_AT = NOW - timedelta(hours=1)


def _build(text: str, links: tuple[str, ...], at: datetime, channel: int, msg_id: int) -> Offer:
    m = MessageData(
        channel_id=channel,
        message_id=msg_id,
        date=at,
        received_at=at,
        text=text,
        links=links,
        fwd_from_channel_id=None,
        fwd_from_message_id=None,
        grouped_id=None,
        has_photo=False,
        source="live",
    )
    offer = offer_from_message(m, sold_out=False, deleted=False, now=NOW)
    assert offer is not None
    return offer


def _coupon() -> Offer:
    return _build(SHOPEE, ("https://s.shopee.com.br/70GSVaUJxC",), COUPON_AT, 10, 1)


def _product(price: int = 5000, at: datetime | None = None, msg_id: int = 2, **kw: object) -> Offer:
    text = f"SSD Kingston 1TB por R$ {price // 100}"
    offer = _build(
        text, ("https://s.shopee.com.br/prod",), at or COUPON_AT - timedelta(hours=2), 20, msg_id
    )
    return replace(offer, **kw)


def _wish(wish_id: int = 1, max_cents: int = 10000) -> WishView:
    return WishView(wish_id, "SSD", (("ssd",),), (), max_cents)


def _ids(offers: list[Offer], wishes: list[WishView] | None = None) -> list[int]:
    targets = coupon_targets(_coupon(), wishes or [_wish()], offers, NOW)
    return [t.offer_message_id for t in targets]


def test_kabum_selecionados_without_minimum_applies_at_any_price() -> None:
    offer = _build(KABUM, ("https://tidd.ly/3VLhRy9",), NOW, 1, 1)
    tier = applicable_tier(
        offer.coupon_tiers, offer.coupon_min_cents, offer.coupon_discount or "", offer.coupons, 100
    )
    assert tier is not None and tier.discount == "10% OFF" and tier.codes == ("KORUJAO",)


def test_shopee_minimum_is_inclusive() -> None:
    c = _coupon()
    args = (c.coupon_tiers, c.coupon_min_cents, c.coupon_discount or "", c.coupons)
    assert applicable_tier(*args, 3999) is None
    assert applicable_tier(*args, 4000) == AppliedTier("R$ 10 OFF", 4000, ("QIP98Q1ZXO",))


def test_mercado_livre_picks_the_tier_by_real_saving() -> None:
    c = _build(MERCADO_LIVRE, ("https://mercadolivre.com/sec/2U6U32Q",), NOW, 1, 1)
    args = (c.coupon_tiers, c.coupon_min_cents, c.coupon_discount or "", c.coupons)
    for price in (69900, 15000):
        tier = applicable_tier(*args, price)
        assert tier is not None
        assert (tier.discount, tier.min_cents) == ("30% OFF", 100)
        assert tier.codes == ("ECONOMIZAML", "DESCONTONAHORA")
        assert tier.cap_cents == 50000


def test_applicable_tier_prefers_the_larger_capped_saving() -> None:
    tiers = (CouponTier("10% OFF", 7900, 4000, ("A",)), CouponTier("15% OFF", None, 2000, ("B",)))
    tier = applicable_tier(tiers, None, "", (), 30000)
    assert tier == AppliedTier("10% OFF", 7900, ("A",), 4000)


def test_equal_savings_go_to_the_higher_minimum() -> None:
    tiers = (
        CouponTier("R$ 10 OFF", None, None, ("A",)),
        CouponTier("R$ 10 OFF", 500, None, ("B",)),
    )
    tier = applicable_tier(tiers, None, "", (), 5000)
    assert tier is not None and tier.codes == ("B",)


def test_no_tier_applies_when_every_minimum_is_above_the_price() -> None:
    tiers = (CouponTier("10% OFF", 7900, None, ("A",)),)
    assert applicable_tier(tiers, None, "", (), 5000) is None


def test_empty_discount_with_met_minimum_is_still_applicable() -> None:
    assert applicable_tier((), 1000, "", ("A",), 5000) == AppliedTier("", 1000, ("A",))


def test_tier_without_codes_falls_back_to_coupon_codes() -> None:
    tiers = (CouponTier("10% OFF", 1000, None, ()),)
    assert applicable_tier(tiers, None, "x", ("TOP",), 2000) == AppliedTier(
        "10% OFF", 1000, ("TOP",)
    )


def test_no_tiers_uses_the_coupon_level_values() -> None:
    assert applicable_tier((), 4000, "R$ 5 OFF", ("A",), 3000) is None
    assert applicable_tier((), None, "R$ 5 OFF", ("A",), 1) == AppliedTier("R$ 5 OFF", None, ("A",))


def test_tie_on_min_goes_to_the_first_tier() -> None:
    tiers = (CouponTier("A", 100, None, ("X",)), CouponTier("B", 100, None, ("Y",)))
    assert applicable_tier(tiers, None, "", (), 500) == AppliedTier("A", 100, ("X",))


def test_recent_window_starts_three_days_before_the_coupon() -> None:
    old = _product(at=COUPON_AT - timedelta(days=3, seconds=1), msg_id=3)
    edge = _product(at=COUPON_AT - timedelta(days=3), msg_id=4)
    assert _ids([old]) == []
    assert _ids([edge]) == [4]


def test_offer_posted_after_the_coupon_but_before_now_is_included() -> None:
    assert _ids([_product(at=COUPON_AT + timedelta(minutes=10))]) == [2]
    assert _ids([_product(at=NOW + timedelta(seconds=1))]) == []


def test_other_unknown_store_deleted_sold_out_unpriced_and_purged_are_excluded() -> None:
    assert _ids([_product(store="amazon")]) == []
    assert _ids([_product(store=None)]) == []
    assert _ids([_product(deleted=True)]) == []
    assert _ids([_product(sold_out=True)]) == []
    assert _ids([_product(price_cents=None)]) == []
    assert _ids([_product(norm_text=None)]) == []


def test_offer_below_the_coupon_minimum_is_excluded() -> None:
    assert _ids([_product(price=3900)], [_wish(max_cents=50000)]) == []


def test_over_max_ceiling() -> None:
    wish = [_wish(max_cents=4000)]
    over = coupon_targets(_coupon(), wish, [_product(price=6000)], NOW)
    assert [(t.offer_price_cents, t.over_max) for t in over] == [(6000, True)]
    assert _ids([_product(price=6100)], wish) == []
    at_max = coupon_targets(_coupon(), [_wish(max_cents=5000)], [_product(price=5000)], NOW)
    assert not at_max[0].over_max


def test_unrelated_wish_does_not_match() -> None:
    other = WishView(1, "TV", (("televisao",),), (), 10000)
    assert _ids([_product()], [other]) == []


def test_cheapest_offer_wins_and_ties_go_to_the_newest() -> None:
    cheap = _product(price=4500, msg_id=5)
    pricey = _product(price=5500, msg_id=6)
    older = _product(price=4500, at=COUPON_AT - timedelta(hours=5), msg_id=7)
    assert _ids([pricey, older, cheap]) == [5]
    assert _ids([older, cheap]) == [5]


def test_two_wishes_give_two_targets_with_the_applied_tier() -> None:
    targets = coupon_targets(_coupon(), [_wish(1), _wish(2)], [_product()], NOW)
    assert [t.wish_id for t in targets] == [1, 2]
    assert targets[0].codes == ("QIP98Q1ZXO",)
    assert (targets[0].discount, targets[0].min_cents) == ("R$ 10 OFF", 4000)


def test_coupon_and_offer_from_different_channels_still_pair() -> None:
    assert _coupon().channel_id != _product().channel_id
    assert _ids([_product()]) == [2]


def test_non_coupon_or_codeless_or_dead_coupon_gives_no_targets() -> None:
    offers = [_product()]
    assert coupon_targets(_coupon(), [_wish()], offers, NOW) != ()
    assert coupon_targets(replace(_coupon(), coupons=()), [_wish()], offers, NOW) == ()
    assert coupon_targets(replace(_coupon(), deleted=True), [_wish()], offers, NOW) == ()
    assert coupon_targets(replace(_coupon(), sold_out=True), [_wish()], offers, NOW) == ()
    assert coupon_targets(replace(_coupon(), store=None), [_wish()], offers, NOW) == ()
    assert coupon_targets(_product(), [_wish()], offers, NOW) == ()
