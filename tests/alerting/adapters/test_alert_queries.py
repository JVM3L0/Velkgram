import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from velkgram.alerting import (
    Alert,
    AlertKind,
    AlertStatus,
    DailyAlerts,
    DailySuppressions,
    LatencySample,
    SuppressionRule,
)
from velkgram.alerting.adapters.sqlite.queries import SqliteAlertQueries
from velkgram.alerting.adapters.sqlite.repository import SqliteAlertRepository
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

D1 = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
D2 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, ["velkgram.shared", "velkgram.alerting"])
    yield c
    c.close()


def _alert(
    channel_id: int,
    message_id: int,
    when: datetime,
    status: AlertStatus = AlertStatus.sent,
    tg: int = 800,
    internal: int = 40,
) -> Alert:
    return Alert(
        id=None,
        wish_id=1,
        channel_id=channel_id,
        message_id=message_id,
        price_cents=1000,
        price_unknown=False,
        dedup_keys=("wp:1:1000",),
        status=status,
        attempts=1,
        delayed_minutes=None,
        created_at=when,
        sent_at=None,
        latency_telegram_ms=tg,
        latency_internal_ms=internal,
        last_error=None,
    )


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> SqliteAlertQueries:
    repo = SqliteAlertRepository(conn)
    repo.add(_alert(1, 1, D1))
    repo.add(_alert(1, 2, D1 + timedelta(hours=1), AlertStatus.failed, tg=900, internal=50))
    repo.add(_alert(2, 1, D1, AlertStatus.expired))
    repo.add(_alert(1, 3, D2))
    # 23:59:59.999999 and 00:00 UTC land on different days
    repo.add(_alert(3, 1, datetime(2026, 11, 3, 23, 59, 59, 999999, tzinfo=UTC)))
    repo.add(_alert(3, 2, datetime(2026, 11, 4, 0, 0, tzinfo=UTC)))
    return SqliteAlertQueries(conn)


def test_history_newest_first_with_paging(seeded: SqliteAlertQueries) -> None:
    page = seeded.history(limit=3, offset=0)
    assert [(a.channel_id, a.message_id) for a in page] == [(1, 3), (3, 2), (3, 1)]
    rest = seeded.history(limit=10, offset=3)
    assert (rest[0].channel_id, rest[0].message_id) == (1, 2)
    assert len(rest) == 3
    assert all(a.id is not None for a in page)


def test_recent_failures_failed_or_expired(seeded: SqliteAlertQueries) -> None:
    result = seeded.recent_failures(10)
    assert [(a.channel_id, a.message_id, a.status) for a in result] == [
        (1, 2, AlertStatus.failed),
        (2, 1, AlertStatus.expired),
    ]
    assert len(seeded.recent_failures(1)) == 1


def test_daily_alert_counts_group_by_day_and_channel(seeded: SqliteAlertQueries) -> None:
    result = seeded.daily_alert_counts(date(2026, 11, 3), date(2026, 11, 4))
    assert result == [
        DailyAlerts(date(2026, 11, 3), 1, 2, 1),
        DailyAlerts(date(2026, 11, 3), 2, 1, 1),
        DailyAlerts(date(2026, 11, 3), 3, 1, 0),
        DailyAlerts(date(2026, 11, 4), 1, 1, 0),
        DailyAlerts(date(2026, 11, 4), 3, 1, 0),
    ]


def test_daily_alert_counts_range_is_inclusive_of_until_day(seeded: SqliteAlertQueries) -> None:
    result = seeded.daily_alert_counts(date(2026, 11, 4), date(2026, 11, 4))
    assert {r.day for r in result} == {date(2026, 11, 4)}
    assert seeded.daily_alert_counts(date(2026, 11, 5), date(2026, 11, 6)) == []


def test_daily_suppressions_and_suppressed_messages(conn: sqlite3.Connection) -> None:
    repo = SqliteAlertRepository(conn)
    repo.add_suppression(1, 1, 1, SuppressionRule.origin, 5, D1)
    repo.add_suppression(1, 2, 1, SuppressionRule.origin, 5, D1)
    repo.add_suppression(1, 3, 1, SuppressionRule.wish_price, 5, D1)
    repo.add_suppression(1, 3, 2, SuppressionRule.wish_text, 5, D1)
    repo.add_suppression(2, 1, 1, SuppressionRule.origin, 5, D2)
    queries = SqliteAlertQueries(conn)
    assert queries.daily_suppressions(date(2026, 11, 3), date(2026, 11, 4)) == [
        DailySuppressions(date(2026, 11, 3), 1, SuppressionRule.origin, 2),
        DailySuppressions(date(2026, 11, 3), 1, SuppressionRule.wish_price, 1),
        DailySuppressions(date(2026, 11, 3), 1, SuppressionRule.wish_text, 1),
        DailySuppressions(date(2026, 11, 4), 2, SuppressionRule.origin, 1),
    ]
    assert queries.suppressed_messages(date(2026, 11, 3), date(2026, 11, 3)) == {
        (1, 1),
        (1, 2),
        (1, 3),
    }
    assert queries.suppressed_messages(date(2026, 11, 4), date(2026, 11, 4)) == {(2, 1)}


def test_latency_samples(seeded: SqliteAlertQueries) -> None:
    result = seeded.latency_samples(date(2026, 11, 3), date(2026, 11, 3))
    assert LatencySample(date(2026, 11, 3), 1, 900, 50) in result
    assert len(result) == 4
    assert all(r.day == date(2026, 11, 3) for r in result)


def test_history_uses_stored_alert_round_trip(conn: sqlite3.Connection) -> None:
    repo = SqliteAlertRepository(conn)
    stored = repo.add(replace(_alert(1, 1, D1), dedup_keys=("a", "b")))
    assert SqliteAlertQueries(conn).history(1, 0) == [stored]


def test_latency_samples_exclude_coupon_alerts_but_daily_counts_include_them(
    conn: sqlite3.Connection,
) -> None:
    repo = SqliteAlertRepository(conn)
    repo.add(_alert(-1001, 1, D1))
    repo.add(replace(_alert(-1001, 2, D1), kind=AlertKind.coupon, dedup_keys=("wcc:1:s:A",)))
    q = SqliteAlertQueries(conn)
    assert len(q.latency_samples(D1.date(), D1.date())) == 1
    assert q.daily_alert_counts(D1.date(), D1.date())[0].alerts == 2
