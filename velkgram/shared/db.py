"""SQLite connection helpers: explicit transactions and state versions."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def bump_version(conn: sqlite3.Connection, name: str) -> int:
    """Increment and return the version of `name`. Call inside `transaction`."""
    row = conn.execute(
        "INSERT INTO state_versions (name, version) VALUES (?, 1) "
        "ON CONFLICT(name) DO UPDATE SET version = version + 1 RETURNING version",
        (name,),
    ).fetchone()
    return int(row[0])


def read_versions(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT name, version FROM state_versions").fetchall()
    return {str(r[0]): int(r[1]) for r in rows}
