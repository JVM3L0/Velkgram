from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from velkgram.apps.cli import main as cli_main
from velkgram.apps.healthcheck import healthcheck, main
from velkgram.ingestion import ConnectionState, Heartbeat

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _hb(age_s: float, state: ConnectionState = "connected") -> Heartbeat:
    return Heartbeat(NOW - timedelta(seconds=age_s), state, None, 0, 0)


def test_healthy_when_recent() -> None:
    assert healthcheck(_hb(10), NOW) == 0


def test_unhealthy_when_stale() -> None:
    assert healthcheck(_hb(90), NOW) == 1
    assert healthcheck(_hb(600), NOW) == 1


def test_unhealthy_when_fatal() -> None:
    assert healthcheck(_hb(1, "fatal"), NOW) == 1


def test_unhealthy_when_missing() -> None:
    assert healthcheck(None, NOW) == 1


def test_main_returns_1_when_db_does_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "absent.db"
    monkeypatch.setenv("DB_PATH", str(db))
    assert main() == 1
    assert not db.exists()


def test_main_returns_1_when_table_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    monkeypatch.setenv("DB_PATH", str(db))
    assert main() == 1


def test_main_returns_1_when_no_heartbeat_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "v.db"))
    assert cli_main(["migrate"]) == 0
    assert main() == 1
