from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.fakes.notifier_state import InMemoryNotifierStateStore
from velkgram.alerting.adapters.sqlite.notifier_state import SqliteNotifierStateStore
from velkgram.alerting.ports.notifier_state import NotifierStateStore, NotifierStatus
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

T0 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[NotifierStateStore]:
    if request.param == "memory":
        yield InMemoryNotifierStateStore()
        return
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, ["velkgram.shared", "velkgram.alerting"])
    yield SqliteNotifierStateStore(conn)
    conn.close()


def test_get_without_row_is_none(store: NotifierStateStore) -> None:
    assert store.get() is None


def test_set_and_get(store: NotifierStateStore) -> None:
    store.set(NotifierStatus.ERROR, "TimeoutError", T0)
    assert store.get() == (NotifierStatus.ERROR, "TimeoutError", T0)


def test_same_values_keep_updated_at(store: NotifierStateStore) -> None:
    store.set(NotifierStatus.OK, None, T0)
    store.set(NotifierStatus.OK, None, T0 + timedelta(minutes=5))
    assert store.get() == (NotifierStatus.OK, None, T0)


def test_changed_detail_or_status_updates(store: NotifierStateStore) -> None:
    store.set(NotifierStatus.ERROR, "a", T0)
    later = T0 + timedelta(minutes=1)
    store.set(NotifierStatus.ERROR, "b", later)
    assert store.get() == (NotifierStatus.ERROR, "b", later)
    latest = T0 + timedelta(minutes=2)
    store.set(NotifierStatus.OK, None, latest)
    assert store.get() == (NotifierStatus.OK, None, latest)


def test_chat_id_round_trip_and_survives_set(store: NotifierStateStore) -> None:
    store.set(NotifierStatus.OK, None, T0)
    store.set_chat_id(-1001)
    assert store.get_chat_id() == -1001
    store.set(NotifierStatus.ERROR, "x", T0 + timedelta(seconds=1))
    assert store.get_chat_id() == -1001


def test_set_chat_id_without_row_is_noop(store: NotifierStateStore) -> None:
    store.set_chat_id(7)
    assert store.get_chat_id() is None
    store.set(NotifierStatus.OK, None, T0)
    assert store.get_chat_id() is None
