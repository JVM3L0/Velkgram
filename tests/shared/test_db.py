import sqlite3
from pathlib import Path

import pytest

from velkgram.shared.db import bump_version, connect, read_versions, transaction
from velkgram.shared.migrate import apply_migrations


def test_connect_pragmas(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    conn.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(RuntimeError), transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
        raise RuntimeError("boom")
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    with transaction(conn):
        conn.execute("INSERT INTO t VALUES (2)")
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1


def test_bump_version_increments(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, ["velkgram.shared"])
    with transaction(conn):
        assert bump_version(conn, "wishlist") == 1
    with transaction(conn):
        assert bump_version(conn, "wishlist") == 2
    assert read_versions(conn) == {"wishlist": 2, "channels": 0}


def test_connection_is_sqlite(tmp_path: Path) -> None:
    assert isinstance(connect(tmp_path / "t.db"), sqlite3.Connection)
