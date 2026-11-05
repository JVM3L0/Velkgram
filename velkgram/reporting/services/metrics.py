"""Usage report: volume, price coverage, alerts, latency and token/cost estimates."""

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from velkgram.reporting.ports.stats import AlertStats, MessageStats, PriceExtractor


@dataclass(frozen=True, slots=True)
class ReportRow:
    day: date
    channel_id: int | None  # None marks the per-day TOTAL row
    messages: int
    priced_ratio: float | None
    alerts: int
    failures: int
    suppressions: dict[str, int]
    latency_p50_ms: float | None  # telegram latency
    latency_p95_ms: float | None  # telegram latency
    latency_internal_p95_ms: float | None
    tokens_all: int
    tokens_after_dedup: int
    cost_all_usd: float | None
    cost_after_dedup_usd: float | None


@dataclass(frozen=True, slots=True)
class Report:
    since: date
    until: date
    rows: list[ReportRow] = field(default_factory=lambda: [])
    day_totals: list[ReportRow] = field(default_factory=lambda: [])


def percentile(samples: Sequence[int], pct: float) -> float | None:
    """Linear interpolation between closest ranks (numpy default); None when empty."""
    if not samples:
        return None
    ordered = sorted(samples)
    pos = (len(ordered) - 1) * pct / 100
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


@dataclass(slots=True)
class _Acc:
    messages: int = 0
    priced: int = 0
    alerts: int = 0
    failures: int = 0
    tokens_all: int = 0
    tokens_dedup: int = 0
    suppressions: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    telegram: list[int] = field(default_factory=lambda: [])
    internal: list[int] = field(default_factory=lambda: [])


def _cost(tokens: int, price_per_mtok_usd: float | None) -> float | None:
    if price_per_mtok_usd is None:
        return None
    return tokens / 1_000_000 * price_per_mtok_usd


def _row(
    day: date, channel_id: int | None, acc: _Acc, price_per_mtok_usd: float | None
) -> ReportRow:
    return ReportRow(
        day=day,
        channel_id=channel_id,
        messages=acc.messages,
        priced_ratio=acc.priced / acc.messages if acc.messages else None,
        alerts=acc.alerts,
        failures=acc.failures,
        suppressions=dict(acc.suppressions),
        latency_p50_ms=percentile(acc.telegram, 50),
        latency_p95_ms=percentile(acc.telegram, 95),
        latency_internal_p95_ms=percentile(acc.internal, 95),
        tokens_all=acc.tokens_all,
        tokens_after_dedup=acc.tokens_dedup,
        cost_all_usd=_cost(acc.tokens_all, price_per_mtok_usd),
        cost_after_dedup_usd=_cost(acc.tokens_dedup, price_per_mtok_usd),
    )


def build_report(
    msgs: MessageStats,
    alerts: AlertStats,
    price: PriceExtractor,
    since: date,
    until: date,
    price_per_mtok_usd: float | None,
) -> Report:
    cells: dict[tuple[date, int], _Acc] = defaultdict(_Acc)
    totals: dict[date, _Acc] = defaultdict(_Acc)

    def both(day: date, channel_id: int) -> tuple[_Acc, _Acc]:
        return cells[(day, channel_id)], totals[day]

    for c in msgs.daily_counts(since, until):
        for acc in both(c.day, c.channel_id):
            acc.messages += c.count
    suppressed = alerts.suppressed_messages(since, until)
    for day, channel_id, message_id, text in msgs.texts(since, until):
        tokens = len(text) // 4
        priced = price(text) is not None
        kept = (channel_id, message_id) not in suppressed
        for acc in both(day, channel_id):
            acc.priced += priced
            acc.tokens_all += tokens
            if kept:
                acc.tokens_dedup += tokens
    for a in alerts.daily_alerts(since, until):
        for acc in both(a.day, a.channel_id):
            acc.alerts += a.alerts
            acc.failures += a.failures
    for s in alerts.daily_suppressions(since, until):
        for acc in both(s.day, s.channel_id):
            acc.suppressions[s.rule] += s.count
    for lat in alerts.latency_samples(since, until):
        for acc in both(lat.day, lat.channel_id):
            acc.telegram.append(lat.telegram_ms)
            acc.internal.append(lat.internal_ms)

    rows = [_row(day, ch, cells[(day, ch)], price_per_mtok_usd) for day, ch in sorted(cells)]
    day_totals = [_row(day, None, totals[day], price_per_mtok_usd) for day in sorted(totals)]
    return Report(since, until, rows, day_totals)
