import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, MIGRATION_PACKAGES)
    yield c
    c.close()


def _insert(conn: sqlite3.Connection, text: str | None) -> None:
    conn.execute(
        "INSERT INTO offers (channel_id, message_id, posted_at, title, has_photo, text, "
        "sold_out, deleted, updated_at) VALUES (1, 1, '2026-01-01T00:00:00Z', 't', 0, ?, 0, 0, "
        "'2026-01-01T00:00:00Z')",
        (text,),
    )


def _hits(conn: sqlite3.Connection, term: str) -> int:
    return len(
        conn.execute("SELECT rowid FROM offers_fts WHERE offers_fts MATCH ?", (term,)).fetchall()
    )


def test_offers_tables_exist(conn: sqlite3.Connection) -> None:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"offers", "offers_fts", "offer_matches", "retro_runs"} <= names
    cols = {r[1] for r in conn.execute("PRAGMA table_info(retro_runs)")}
    assert "fingerprint" in cols


def test_fts_indexes_text_and_skips_null_text(conn: sqlite3.Connection) -> None:
    _insert(conn, "SSD Kingston 1TB")
    assert _hits(conn, "kingston") == 1
    conn.execute("UPDATE offers SET text = NULL")
    assert _hits(conn, "kingston") == 0


def test_fts_ignores_accents(conn: sqlite3.Connection) -> None:
    _insert(conn, "promoção")
    assert _hits(conn, "promocao") == 1
