import pytest

from velkgram.offers.domain.insight import PriceVerdict, price_insight


@pytest.mark.parametrize(
    ("current", "history", "verdict"),
    [
        (9000, [10000, 10000, 10000], PriceVerdict.below),
        (9500, [10000, 10000, 10000], PriceVerdict.average),  # exactly -5 %
        (10500, [10000, 10000, 10000], PriceVerdict.average),  # exactly +5 %
        (10501, [10000, 10000, 10000], PriceVerdict.above),
        (9499, [10000, 10000, 10000], PriceVerdict.below),
        (10000, [10000, 10000], PriceVerdict.unknown),  # fewer than 3 points
        (None, [10000, 10000, 10000], PriceVerdict.unknown),
        (10000, [], PriceVerdict.unknown),
    ],
)
def test_verdict_against_the_range_average(
    current: int | None, history: list[int], verdict: PriceVerdict
) -> None:
    assert price_insight(current, history).verdict is verdict


def test_average_is_rounded_half_up_and_missing_when_unknown() -> None:
    assert price_insight(100, [100, 101, 101]).average_cents == 101
    assert price_insight(100, [100]).average_cents is None
