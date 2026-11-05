"""Whether an offer's price can be compared with other offers of the same product (pure)."""

from velkgram.offers.domain.coupon import starts_with_coupon_word
from velkgram.shared.deals import listed_prices


def is_comparable(title: str, text: str | None) -> bool:
    """Coupons and posts listing several different prices say nothing about one product."""
    if starts_with_coupon_word(title):
        return False
    return text is None or len(set(listed_prices(text))) < 2
