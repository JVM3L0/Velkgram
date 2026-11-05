from datetime import date

from velkgram.reporting.ports.stats import (
    DailyAlertStat,
    DailyMessageCount,
    DailySuppressionStat,
    LatencyStat,
)
from velkgram.reporting.services.metrics import build_report

D1 = date(2026, 11, 1)
D2 = date(2026, 11, 2)


class FakeMsgs:
    def __init__(self, texts: list[tuple[date, int, int, str]]) -> None:
        self._texts = texts

    def daily_counts(self, since: date, until: date) -> list[DailyMessageCount]:
        counts: dict[tuple[date, int], int] = {}
        for day, ch, _mid, _t in self._texts:
            counts[(day, ch)] = counts.get((day, ch), 0) + 1
        return [DailyMessageCount(d, c, n) for (d, c), n in sorted(counts.items())]

    def texts(self, since: date, until: date) -> list[tuple[date, int, int, str]]:
        return list(self._texts)


class FakeAlerts:
    def __init__(
        self,
        suppressed: set[tuple[int, int]] | None = None,
        latencies: list[LatencyStat] | None = None,
    ) -> None:
        self._suppressed = suppressed or set()
        self._latencies = latencies or []

    def daily_alerts(self, since: date, until: date) -> list[DailyAlertStat]:
        return [DailyAlertStat(D1, 1, alerts=2, failures=1)]

    def daily_suppressions(self, since: date, until: date) -> list[DailySuppressionStat]:
        return [DailySuppressionStat(D1, 1, "origin", 3)]

    def suppressed_messages(self, since: date, until: date) -> set[tuple[int, int]]:
        return self._suppressed

    def latency_samples(self, since: date, until: date) -> list[LatencyStat]:
        return self._latencies


def price(text: str) -> int | None:
    return 100 if "R$" in text else None


def test_priced_ratio_per_day_channel() -> None:
    msgs = FakeMsgs([(D1, 1, 1, "R$ 10"), (D1, 1, 2, "oi"), (D1, 2, 3, "oi"), (D2, 1, 4, "R$ 5")])
    report = build_report(msgs, FakeAlerts(), price, D1, D2, None)
    by_key = {(r.day, r.channel_id): r for r in report.rows}
    assert by_key[(D1, 1)].priced_ratio == 0.5
    assert by_key[(D1, 2)].priced_ratio == 0.0
    assert by_key[(D2, 1)].priced_ratio == 1.0
    assert by_key[(D1, 1)].alerts == 2
    assert by_key[(D1, 1)].failures == 1
    assert by_key[(D1, 1)].suppressions == {"origin": 3}
    assert by_key[(D1, 2)].suppressions == {}


def test_percentiles() -> None:
    lat = [LatencyStat(D1, 1, ms, ms * 2) for ms in (100, 200, 300, 400)]
    msgs = FakeMsgs([(D1, 1, 1, "x"), (D1, 2, 2, "y")])
    report = build_report(msgs, FakeAlerts(latencies=lat), price, D1, D1, None)
    by_key = {(r.day, r.channel_id): r for r in report.rows}
    assert by_key[(D1, 1)].latency_p50_ms == 250
    assert by_key[(D1, 1)].latency_p95_ms == 385
    assert by_key[(D1, 1)].latency_internal_p95_ms == 770
    assert by_key[(D1, 2)].latency_p50_ms is None
    assert by_key[(D1, 2)].latency_p95_ms is None


def test_tokens_after_dedup_excludes_suppressed() -> None:
    msgs = FakeMsgs([(D1, 1, 1, "a" * 40), (D1, 1, 2, "b" * 80)])
    report = build_report(msgs, FakeAlerts(suppressed={(1, 2)}), price, D1, D1, 2.0)
    row = report.rows[0]
    assert row.tokens_all == 30
    assert row.tokens_after_dedup == 10
    assert row.cost_all_usd == 30 / 1_000_000 * 2.0
    assert row.cost_after_dedup_usd == 10 / 1_000_000 * 2.0


def test_cost_none_without_price() -> None:
    msgs = FakeMsgs([(D1, 1, 1, "a" * 40)])
    row = build_report(msgs, FakeAlerts(), price, D1, D1, None).rows[0]
    assert row.cost_all_usd is None
    assert row.cost_after_dedup_usd is None
