import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.fakes.repositories import InMemoryAlertRepository
from velkgram.alerting import Alert, AlertRepository, AlertStatus, SuppressionRule
from velkgram.alerting.adapters.sqlite.repository import SqliteAlertRepository
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@dataclass
class RepoHandle:
    repo: AlertRepository
    memory: InMemoryAlertRepository | None = None
    conn: sqlite3.Connection | None = None

    def suppressions(self) -> list[tuple[int, int, int, str, int, datetime]]:
        if self.memory is not None:
            return list(self.memory.suppressions)
        assert self.conn is not None
        rows = self.conn.execute(
            "SELECT channel_id, message_id, wish_id, rule, matched_alert_id, created_at "
            "FROM alert_suppressions ORDER BY rowid"
        ).fetchall()
        return [
            (
                r["channel_id"],
                r["message_id"],
                r["wish_id"],
                r["rule"],
                r["matched_alert_id"],
                datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]


@pytest.fixture(params=["memory", "sqlite"])
def handle(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[RepoHandle]:
    if request.param == "memory":
        memory = InMemoryAlertRepository()
        yield RepoHandle(memory, memory=memory)
        return
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, ["velkgram.shared", "velkgram.alerting"])
    yield RepoHandle(SqliteAlertRepository(conn), conn=conn)
    conn.close()


def _alert(
    message_id: int = 1,
    created_at: datetime = T0,
    status: AlertStatus = AlertStatus.pending,
    **kw: object,
) -> Alert:
    base = Alert(
        id=None,
        wish_id=3,
        channel_id=100,
        message_id=message_id,
        price_cents=29990,
        price_unknown=False,
        dedup_keys=("org:3:100:1", "wp:3:29990", "wt:3:abc"),
        status=status,
        attempts=0,
        delayed_minutes=None,
        created_at=created_at,
        sent_at=None,
        latency_telegram_ms=800,
        latency_internal_ms=40,
        last_error=None,
    )
    return replace(base, **kw)


def test_add_assigns_id_and_round_trips(handle: RepoHandle) -> None:
    stored = handle.repo.add(_alert())
    assert stored.id is not None
    assert replace(stored, id=None) == _alert()
    assert handle.repo.list_since(T0 - timedelta(hours=1)) == [stored]


def test_round_trip_optional_fields(handle: RepoHandle) -> None:
    stored = handle.repo.add(
        _alert(
            price_cents=None,
            price_unknown=True,
            dedup_keys=(),
            delayed_minutes=12,
            sent_at=T0 + timedelta(seconds=3),
            last_error="boom",
            status=AlertStatus.sent,
            attempts=2,
        )
    )
    assert handle.repo.list_since(T0) == [stored]
    assert stored.dedup_keys == ()
    assert stored.price_cents is None


def test_ids_are_distinct(handle: RepoHandle) -> None:
    a = handle.repo.add(_alert(1))
    b = handle.repo.add(_alert(2))
    assert a.id != b.id


def test_update_persists_changes(handle: RepoHandle) -> None:
    stored = handle.repo.add(_alert())
    sent = replace(
        stored,
        status=AlertStatus.sent,
        attempts=1,
        sent_at=T0 + timedelta(seconds=2),
        last_error="x",
    )
    handle.repo.update(sent)
    assert handle.repo.list_since(T0) == [sent]


def test_list_since_is_inclusive_and_ordered(handle: RepoHandle) -> None:
    old = handle.repo.add(_alert(1, T0 - timedelta(hours=2)))
    edge = handle.repo.add(_alert(2, T0))
    new = handle.repo.add(_alert(3, T0 + timedelta(minutes=5)))
    assert handle.repo.list_since(T0) == [edge, new]
    assert handle.repo.list_since(T0 - timedelta(hours=3)) == [old, edge, new]


def test_list_retryable_failed_and_stuck_pending(handle: RepoHandle) -> None:
    since = T0 - timedelta(minutes=30)
    stuck_before = T0 - timedelta(minutes=1)
    failed = handle.repo.add(_alert(1, T0 - timedelta(minutes=10), AlertStatus.failed))
    failed_old = handle.repo.add(_alert(2, since - timedelta(minutes=1), AlertStatus.failed))
    stuck = handle.repo.add(_alert(3, T0 - timedelta(minutes=5), AlertStatus.pending))
    fresh = handle.repo.add(_alert(4, T0, AlertStatus.pending))
    ancient = handle.repo.add(_alert(5, since - timedelta(hours=1), AlertStatus.pending))
    handle.repo.add(_alert(6, T0 - timedelta(minutes=5), AlertStatus.sent))
    handle.repo.add(_alert(7, T0 - timedelta(minutes=5), AlertStatus.expired))
    result = handle.repo.list_retryable(since, stuck_before)
    assert result == [failed, stuck]
    for excluded in (failed_old, fresh, ancient):
        assert excluded not in result


def test_list_retryable_boundaries(handle: RepoHandle) -> None:
    since = T0 - timedelta(minutes=30)
    stuck_before = T0 - timedelta(minutes=1)
    at_since = handle.repo.add(_alert(1, since, AlertStatus.failed))
    pending_at_stuck = handle.repo.add(_alert(2, stuck_before, AlertStatus.pending))
    pending_at_since = handle.repo.add(_alert(3, since, AlertStatus.pending))
    assert handle.repo.list_retryable(since, stuck_before) == [at_since, pending_at_since]
    assert pending_at_stuck not in handle.repo.list_retryable(since, stuck_before)


def test_list_failed_before(handle: RepoHandle) -> None:
    old = handle.repo.add(_alert(1, T0 - timedelta(hours=2), AlertStatus.failed))
    handle.repo.add(_alert(2, T0, AlertStatus.failed))
    handle.repo.add(_alert(3, T0 - timedelta(hours=3), AlertStatus.sent))
    handle.repo.add(_alert(4, T0 - timedelta(hours=3), AlertStatus.pending))
    assert handle.repo.list_failed_before(T0) == [old]


def test_has_alert_for_message(handle: RepoHandle) -> None:
    handle.repo.add(_alert(5))
    assert handle.repo.has_alert_for_message(100, 5) is True
    assert handle.repo.has_alert_for_message(100, 6) is False
    assert handle.repo.has_alert_for_message(101, 5) is False


def test_add_suppression_records_row(handle: RepoHandle) -> None:
    at = T0 + timedelta(seconds=1)
    handle.repo.add_suppression(100, 7, 3, SuppressionRule.wish_price, 11, at)
    handle.repo.add_suppression(100, 8, 3, SuppressionRule.origin, 11, at)
    assert handle.suppressions() == [
        (100, 7, 3, "wish_price", 11, at),
        (100, 8, 3, "origin", 11, at),
    ]
    assert handle.repo.has_alert_for_message(100, 7) is False
