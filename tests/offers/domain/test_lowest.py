from datetime import UTC, datetime, timedelta

from velkgram.offers.domain.lowest import current_lowest, daily_lowest

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _o(days: float, price: int, store: str = "amazon") -> tuple[datetime, int, str]:
    return T0 + timedelta(days=days), price, store


def test_daily_lowest_keeps_the_cheapest_offer_of_each_day_across_stores() -> None:
    offers = [
        _o(0, 150000, "amazon"),
        _o(0.1, 144400, "kabum"),  # same day, cheaper, another store
        _o(1, 149000, "amazon"),
        _o(1.2, 151000, "magalu"),
    ]
    assert daily_lowest(offers, None) == [
        (T0 + timedelta(days=0.1), 144400),
        (T0 + timedelta(days=1), 149000),
    ]


def test_daily_lowest_is_oldest_first_and_can_be_limited_to_a_window() -> None:
    offers = [_o(5, 100), _o(0, 300), _o(2, 200)]
    assert [p for _, p in daily_lowest(offers, None)] == [300, 200, 100]
    assert [p for _, p in daily_lowest(offers, T0 + timedelta(days=1))] == [200, 100]


def test_daily_lowest_of_nothing_is_empty() -> None:
    assert daily_lowest([], None) == []


def test_current_lowest_is_the_cheapest_latest_price_of_any_store_within_the_window() -> None:
    now = T0 + timedelta(days=10)
    offers = [
        _o(0, 100000, "kabum"),  # too old for a 5-day window
        _o(6, 150000, "amazon"),
        _o(8, 140000, "amazon"),  # amazon's latest replaces the older one
        _o(9, 145000, "magalu"),
    ]
    assert current_lowest(offers, now, 5) == 140000


def test_current_lowest_falls_back_to_the_latest_price_when_everything_is_old() -> None:
    now = T0 + timedelta(days=100)
    assert current_lowest([_o(0, 100000, "kabum"), _o(3, 90000, "amazon")], now, 14) == 90000
    assert current_lowest([], now, 14) is None
