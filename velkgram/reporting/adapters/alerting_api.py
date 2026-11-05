"""Adapter: alerting read queries -> reporting `AlertStats`; price extractor."""

from datetime import date

from velkgram.alerting import AlertQueries, SuppressionRule, extract_price
from velkgram.reporting.ports.stats import (
    DailyAlertStat,
    DailySuppressionStat,
    LatencyStat,
    PriceExtractor,
)

# Report labels for suppression rules whose enum value is not the label (pt-BR for coupons).
_RULE_LABELS = {SuppressionRule.wish_coupon: "cupom"}


def price_extractor() -> PriceExtractor:
    return extract_price


class AlertingAlertStats:
    def __init__(self, queries: AlertQueries) -> None:
        self._q = queries

    def daily_alerts(self, since: date, until: date) -> list[DailyAlertStat]:
        return [
            DailyAlertStat(a.day, a.channel_id, a.alerts, a.failures)
            for a in self._q.daily_alert_counts(since, until)
        ]

    def daily_suppressions(self, since: date, until: date) -> list[DailySuppressionStat]:
        return [
            DailySuppressionStat(
                s.day, s.channel_id, _RULE_LABELS.get(s.rule, s.rule.value), s.count
            )
            for s in self._q.daily_suppressions(since, until)
        ]

    def suppressed_messages(self, since: date, until: date) -> set[tuple[int, int]]:
        return self._q.suppressed_messages(since, until)

    def latency_samples(self, since: date, until: date) -> list[LatencyStat]:
        return [
            LatencyStat(s.day, s.channel_id, s.telegram_ms, s.internal_ms)
            for s in self._q.latency_samples(since, until)
        ]
