import sqlite3
from pathlib import Path

import pytest

from tests.fakes.bot_client import FakeBotClient
from velkgram.alerting.adapters.sqlite.notifier_state import SqliteNotifierStateStore
from velkgram.alerting.ports.notifier_state import NotifierStatus
from velkgram.apps import cli
from velkgram.apps.cli import MIGRATION_PACKAGES, main
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

TOKEN = "123:SECRETTOKEN"


def _setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    notifier: str = "telegram",
    chat: str | None = "777",
    stored_chat: int | None = None,
) -> FakeBotClient:
    db = tmp_path / "v.db"
    monkeypatch.setenv("DB_PATH", str(db))
    monkeypatch.setenv("NOTIFIER", notifier)
    monkeypatch.setenv("ALERT_BOT_TOKEN", TOKEN)
    if chat is None:
        monkeypatch.delenv("ALERT_CHAT_ID", raising=False)
    else:
        monkeypatch.setenv("ALERT_CHAT_ID", chat)
    if stored_chat is not None:
        conn: sqlite3.Connection = connect(db)
        apply_migrations(conn, MIGRATION_PACKAGES)
        from datetime import UTC, datetime

        store = SqliteNotifierStateStore(conn)
        store.set(NotifierStatus.OK, None, datetime.now(UTC))
        store.set_chat_id(stored_chat)
        conn.close()
    bot = FakeBotClient()
    monkeypatch.setattr(cli, "_make_bot_client", lambda _settings: bot)
    return bot


def test_notify_test_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bot = _setup(tmp_path, monkeypatch)
    assert main(["notify-test"]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == "enviado"
    assert bot.sent == [(777, "Velkgram: teste de alerta ✅", True)]
    assert bot.disconnects >= 1
    assert TOKEN not in out.out + out.err


def test_notify_test_uses_stored_chat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _setup(tmp_path, monkeypatch, chat=None, stored_chat=55)
    assert main(["notify-test"]) == 0
    assert bot.sent[0][0] == 55


def test_notify_test_send_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bot = _setup(tmp_path, monkeypatch)
    bot.send_error = RuntimeError(f"boom {TOKEN}")
    assert main(["notify-test"]) == 1
    out = capsys.readouterr()
    assert out.out.strip().startswith("falhou: RuntimeError")
    assert TOKEN not in out.out + out.err
    assert bot.disconnects >= 1


def test_notify_test_failed_login_prints_state_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bot = _setup(tmp_path, monkeypatch)
    bot.start_error = RuntimeError(f"bad {TOKEN}")
    assert main(["notify-test"]) == 1
    out = capsys.readouterr()
    assert out.out.strip().splitlines()[-1] == "falhou: bot_unavailable (RuntimeError)"
    assert TOKEN not in out.out + out.err


def test_notify_test_without_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bot = _setup(tmp_path, monkeypatch, chat=None)
    assert main(["notify-test"]) == 1
    out = capsys.readouterr()
    assert out.out.strip() == "falhou: sem chat (defina ALERT_CHAT_ID ou rode o coletor uma vez)"
    assert bot.sent == [] and bot.start_calls == []
    assert TOKEN not in out.out + out.err


def test_notify_test_requires_telegram_notifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bot = _setup(tmp_path, monkeypatch, notifier="log")
    assert main(["notify-test"]) == 2
    assert capsys.readouterr().err.strip() != ""
    assert bot.start_calls == []
