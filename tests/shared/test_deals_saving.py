import pytest

from velkgram.shared.deals import LOW_CAP_PCT, Saving, coupon_saving, min_not_met


def test_low_cap_threshold_is_five_percent() -> None:
    assert LOW_CAP_PCT == 5


@pytest.mark.parametrize(
    ("min_cents", "price", "expected"),
    [(None, 100, False), (7900, 5000, True), (5000, 5000, False), (100, 5000, False)],
)
def test_min_not_met(min_cents: int | None, price: int, expected: bool) -> None:
    assert min_not_met(min_cents, price) is expected


@pytest.mark.parametrize(
    ("discount", "min_cents", "cap", "price", "expected"),
    [
        ("R$ 90 OFF", 69900, None, 100000, Saving(9000, False, False)),
        ("R$ 90 OFF", None, None, 5000, Saving(5000, False, False)),
        ("R$ 9,90 OFF", None, None, 10000, Saving(990, False, False)),
        ("15% OFF", None, None, 151700, Saving(22755, False, False)),
        ("15% OFF", None, 4000, 151700, Saving(4000, True, True)),
        ("20% OFF", None, 5000, 10000, Saving(2000, False, False)),
        ("50% OFF", None, 500, 10000, Saving(500, True, False)),
        ("15% OFF", None, None, 999, Saving(149, False, False)),
        ("10% OFF", 7900, None, 5000, None),
        ("10% OFF", 5000, None, 5000, Saving(500, False, False)),
        ("", None, None, 1000, None),
    ],
)
def test_coupon_saving(
    discount: str, min_cents: int | None, cap: int | None, price: int, expected: Saving | None
) -> None:
    assert coupon_saving(discount, min_cents, cap, price) == expected
