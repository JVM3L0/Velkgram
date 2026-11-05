from datetime import UTC, datetime, timedelta

from velkgram.offers.domain.stats import product_stats

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


def test_stats_ignore_unknown_prices() -> None:
    s = product_stats([(_ago(1), None), (_ago(2), 500)], NOW)
    assert (s.lowest_cents, s.avg_30d_cents, s.last_cents) == (500, 500, 500)


def test_avg_30d_uses_only_last_30_days() -> None:
    s = product_stats([(_ago(5), 200), (_ago(40), 1000)], NOW)
    assert s.avg_30d_cents == 200
    assert s.lowest_cents == 200


def test_avg_rounds_half_up() -> None:
    assert product_stats([(_ago(1), 100), (_ago(2), 101)], NOW).avg_30d_cents == 101


def test_last_is_most_recent_priced_match() -> None:
    s = product_stats([(_ago(10), 300), (_ago(1), 900), (_ago(0), None)], NOW)
    assert s.last_cents == 900


def test_empty_matches_give_empty_stats() -> None:
    s = product_stats([], NOW)
    assert (s.lowest_cents, s.avg_30d_cents, s.last_cents, s.match_count) == (None, None, None, 0)


def test_match_count_includes_unknown_prices() -> None:
    assert product_stats([(_ago(1), None), (_ago(2), 5)], NOW).match_count == 2


def test_no_priced_match_in_window_gives_no_average() -> None:
    assert product_stats([(_ago(60), 5)], NOW).avg_30d_cents is None
