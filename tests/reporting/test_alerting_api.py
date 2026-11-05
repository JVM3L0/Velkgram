from datetime import date

from velkgram.alerting import DailySuppressions, SuppressionRule
from velkgram.reporting.adapters.alerting_api import AlertingAlertStats

D = date(2026, 11, 4)


class _Queries:
    def daily_suppressions(self, since: date, until: date) -> list[DailySuppressions]:
        return [
            DailySuppressions(D, 1, SuppressionRule.origin, 2),
            DailySuppressions(D, 1, SuppressionRule.wish_coupon, 4),
        ]


def test_suppression_stats_label_wish_coupon_as_cupom() -> None:
    stats = AlertingAlertStats(_Queries())  # type: ignore[arg-type]
    result = stats.daily_suppressions(D, D)
    assert [(s.rule, s.count) for s in result] == [("origin", 2), ("cupom", 4)]
