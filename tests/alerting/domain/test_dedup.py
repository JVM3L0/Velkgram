from datetime import UTC, datetime, timedelta

from velkgram.alerting.domain.dedup import (
    DedupCache,
    DedupKey,
    coupon_content_key,
    coupon_origin_key,
    origin_key,
    price_key,
    rule_for_key,
    text_key,
)
from velkgram.alerting.domain.models import SuppressionRule

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def test_origin_key_uses_forward_origin() -> None:
    assert origin_key(1, 2, 3, None, None) == "org:1:2:3"
    assert origin_key(1, 2, 3, 20, 30) == "org:1:20:30"


def test_rule_for_key() -> None:
    assert rule_for_key(origin_key(1, 2, 3, None, None)) is SuppressionRule.origin
    assert rule_for_key(price_key(1, 5000)) is SuppressionRule.wish_price
    assert rule_for_key(text_key(1, "ssd")) is SuppressionRule.wish_text
    assert price_key(1, 5000) == "wp:1:5000"
    assert text_key(1, "ssd").startswith("wt:1:")


def test_cache_hit_within_window_and_miss_after() -> None:
    cache = DedupCache(timedelta(minutes=30))
    key: DedupKey = (SuppressionRule.wish_price, "wp:1:5000")
    cache.remember([key], 7, T0)
    assert cache.find([key], T0 + timedelta(minutes=29)) == (SuppressionRule.wish_price, 7)
    assert cache.find([key], T0 + timedelta(minutes=31)) is None
    cache.prune(T0 + timedelta(minutes=31))
    assert cache.find([key], T0) is None


def test_find_returns_first_rule_in_order() -> None:
    cache = DedupCache(timedelta(minutes=30))
    a: DedupKey = (SuppressionRule.origin, "org:1:2:3")
    b: DedupKey = (SuppressionRule.wish_price, "wp:1:5000")
    cache.remember([a], 1, T0)
    cache.remember([b], 2, T0)
    assert cache.find([b, a], T0) == (SuppressionRule.wish_price, 2)
    assert cache.find([a, b], T0) == (SuppressionRule.origin, 1)


def test_coupon_key_formats() -> None:
    assert coupon_origin_key(1, 2, 3, None, None) == "wco:1:2:3"
    assert coupon_origin_key(1, 2, 3, 20, 30) == "wco:1:20:30"
    assert coupon_origin_key(1, 2, 3, 20, None) == "wco:1:2:3"
    assert coupon_content_key(1, "amazon", ("B2", "A1")) == "wcc:1:amazon:A1,B2"
    assert coupon_content_key(1, "amazon", ("A1",)) == "wcc:1:amazon:A1"


def test_rule_for_coupon_keys() -> None:
    assert rule_for_key("wco:1:2:3") is SuppressionRule.wish_coupon
    assert rule_for_key("wcc:1:amazon:A1") is SuppressionRule.wish_coupon


def test_per_rule_windows() -> None:
    cache = DedupCache(timedelta(minutes=30), {SuppressionRule.wish_coupon: timedelta(days=3)})
    coupon: DedupKey = (SuppressionRule.wish_coupon, "wco:1:2:3")
    price: DedupKey = (SuppressionRule.wish_price, "wp:1:5000")
    cache.remember([coupon, price], 7, T0)
    assert cache.find([coupon], T0 + timedelta(days=2)) == (SuppressionRule.wish_coupon, 7)
    assert cache.find([coupon], T0 + timedelta(days=3, seconds=1)) is None
    assert cache.find([price], T0 + timedelta(minutes=31)) is None
    cache.prune(T0 + timedelta(days=2))
    assert cache.find([coupon], T0 + timedelta(days=2)) is not None
    assert cache.find([price], T0) is None
    cache.prune(T0 + timedelta(days=3, seconds=1))
    assert cache.find([coupon], T0) is None
