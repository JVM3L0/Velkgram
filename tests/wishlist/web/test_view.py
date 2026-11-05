import pytest

from velkgram.wishlist.web.view import WishCardStats, is_below_alert


def _stats(last: int | None, previous: int | None) -> WishCardStats:
    return WishCardStats(
        last_price_cents=last, match_count=2, sparkline_svg="", previous_price_cents=previous
    )


@pytest.mark.parametrize(
    ("last", "previous", "expected"),
    [
        (20000, 25000, -20),
        (27500, 25000, 10),
        (25000, 25000, None),  # no change: nothing to show
        (20000, None, None),
        (None, 25000, None),
        (24990, 25000, None),  # rounds to 0 %
        (22222, 25000, -11),
        (100, 0, None),  # a zero previous price cannot be a base
    ],
)
def test_delta_percent_is_the_rounded_change_since_the_previous_price(
    last: int | None, previous: int | None, expected: int | None
) -> None:
    assert _stats(last, previous).delta_percent == expected


@pytest.mark.parametrize(
    ("last", "limit", "expected"),
    [(30000, 30000, True), (29999, 30000, True), (30001, 30000, False), (None, 30000, False)],
)
def test_below_alert_means_last_comparable_price_at_or_under_the_limit(
    last: int | None, limit: int, expected: bool
) -> None:
    assert is_below_alert(last, limit) is expected
