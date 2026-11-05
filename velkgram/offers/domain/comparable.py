"""Whether an offer's price can be compared with other offers of the same product (pure)."""

import unicodedata

from velkgram.shared.deals import listed_prices


def _starts_with_coupon(title: str) -> bool:
    decomposed = unicodedata.normalize("NFKD", title.strip().lower())
    plain = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return plain.startswith("cupom")


def is_comparable(title: str, text: str | None) -> bool:
    """Coupons and posts listing several different prices say nothing about one product."""
    if _starts_with_coupon(title):
        return False
    return text is None or len(set(listed_prices(text))) < 2
