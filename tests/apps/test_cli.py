import sqlite3
from pathlib import Path

import pytest

from velkgram.apps.cli import main


def test_migrate_creates_all_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "nested" / "v.db"
    monkeypatch.setenv("DB_PATH", str(db))
    assert main(["migrate"]) == 0
    assert "velkgram.shared/" in capsys.readouterr().out
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"wishes", "channels", "messages", "alerts"} <= names


def test_cli_help_lists_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for cmd in ("migrate", "login", "hash-password"):
        assert cmd in out


def test_hash_password_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "pw")
    assert main(["hash-password"]) == 0
    assert capsys.readouterr().out.strip().startswith("scrypt$16384$8$1$")


def test_hash_password_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["a", "b"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert main(["hash-password"]) == 1


def test_hash_password_rejects_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "")
    assert main(["hash-password"]) == 1
    assert capsys.readouterr().err


def test_login_assumptions_hold_without_network() -> None:
    from dataclasses import replace

    from telethon.sessions import StringSession

    from velkgram.ingestion.adapters.telethon.client import build_client
    from velkgram.shared.config import load_settings

    settings = load_settings({"TG_API_ID": "1", "TG_API_HASH": "x", "TG_SESSION": "abc"})
    client = build_client(replace(settings, tg_session=None))
    assert isinstance(client.session, StringSession)
    assert StringSession.save(client.session) == ""
