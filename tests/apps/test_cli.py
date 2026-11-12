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
    for cmd in ("migrate", "login", "hash-password", "notify-test"):
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

    settings = load_settings({"TG_API_ID": "1", "TG_API_HASH": "x"})
    client = build_client(replace(settings, tg_session=None))
    assert isinstance(client.session, StringSession)
    assert StringSession.save(client.session) == ""


def test_report_runs_on_empty_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "v.db"))
    assert main(["migrate"]) == 0
    capsys.readouterr()
    assert main(["report", "--since", "2026-11-01", "--until", "2026-11-02"]) == 0
    assert "latency_telegram_ms" in capsys.readouterr().out


def test_report_rejects_invalid_date(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["report", "--since", "11/01/2026"])
    assert exc.value.code == 2
    assert "invalid date" in capsys.readouterr().err


def _user_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "u.db"
    monkeypatch.setenv("DB_PATH", str(db))
    assert main(["migrate"]) == 0
    return db


def _users(db: Path) -> list[tuple[str, str, int]]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT username, role, enabled FROM users ORDER BY id").fetchall()
    finally:
        conn.close()
    return [(r[0], r[1], r[2]) for r in rows]


def test_user_add_creates_an_account_with_a_prompted_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _user_db(tmp_path, monkeypatch)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "senha-forte-1")
    assert main(["user", "add", "ana"]) == 0
    assert main(["user", "add", "bia", "--admin"]) == 0
    assert _users(db) == [("admin", "admin", 1), ("ana", "user", 1), ("bia", "admin", 1)]


def test_user_add_rejects_a_duplicate_or_weak_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _user_db(tmp_path, monkeypatch)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "senha-forte-1")
    assert main(["user", "add", "ana"]) == 0
    assert main(["user", "add", "ana"]) == 1
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "curta")
    assert main(["user", "add", "bia"]) == 1
    assert capsys.readouterr().err


def test_user_passwd_disable_enable_and_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _user_db(tmp_path, monkeypatch)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "senha-forte-1")
    main(["user", "add", "ana"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "outra-senha-2")
    assert main(["user", "passwd", "ana"]) == 0
    assert main(["user", "disable", "ana"]) == 0
    assert _users(db)[1] == ("ana", "user", 0)
    assert main(["user", "enable", "ana"]) == 0
    assert _users(db)[1] == ("ana", "user", 1)
    capsys.readouterr()
    assert main(["user", "list"]) == 0
    out = capsys.readouterr().out
    assert "ana" in out and "admin" in out
    assert main(["user", "passwd", "ghost"]) == 1


def test_user_chat_sets_the_telegram_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _user_db(tmp_path, monkeypatch)
    assert main(["user", "chat", "admin", "12345"]) == 0
    conn = sqlite3.connect(db)
    try:
        assert (
            conn.execute("SELECT telegram_chat_id FROM users WHERE id = 1").fetchone()[0] == 12345
        )
    finally:
        conn.close()
    assert main(["user", "chat", "admin", "abc"]) == 1


def test_migrate_seeds_the_admin_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from velkgram.apps.web.auth import hash_password

    monkeypatch.setenv("DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("WEB_PASSWORD_HASH", hash_password("segredo-1"))
    monkeypatch.setenv("ALERT_CHAT_ID", "777")
    assert main(["migrate"]) == 0
    conn = sqlite3.connect(tmp_path / "m.db")
    try:
        pw, chat = conn.execute(
            "SELECT password_hash, telegram_chat_id FROM users WHERE id=1"
        ).fetchone()
    finally:
        conn.close()
    assert pw.startswith("scrypt$") and chat == 777
