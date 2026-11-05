from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from velkgram.apps.collector.retention import RetentionSchedule

SP = ZoneInfo("America/Sao_Paulo")


def test_schedule_due_once_per_local_day() -> None:
    s = RetentionSchedule(SP)
    now = datetime(2026, 11, 4, 7, 0, tzinfo=UTC)  # 04:00 in Sao Paulo
    assert s.due(now)
    s.mark_ran(now)
    assert not s.due(datetime(2026, 11, 4, 20, 0, tzinfo=UTC))
    assert s.due(datetime(2026, 11, 5, 7, 0, tzinfo=UTC))


def test_schedule_not_due_before_4am_local() -> None:
    s = RetentionSchedule(SP)
    assert not s.due(datetime(2026, 11, 4, 6, 59, tzinfo=UTC))  # 03:59 local
