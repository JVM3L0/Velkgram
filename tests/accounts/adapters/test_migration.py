import sqlite3
from importlib.resources import files
from pathlib import Path

from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations


def test_migration_seeds_the_admin_without_a_password(tmp_path: Path) -> None:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, MIGRATION_PACKAGES)
    row = c.execute("SELECT id, username, password_hash, role, enabled FROM users").fetchall()
    assert [tuple(r) for r in row] == [(1, "admin", "", "admin", 1)]
    c.close()


def test_existing_wishes_belong_to_the_admin_after_the_migration(tmp_path: Path) -> None:
    c = connect(tmp_path / "old.db")
    c.executescript((files("velkgram.wishlist") / "migrations" / "001_wishes.sql").read_text())
    c.execute(
        "CREATE TABLE schema_migrations (package TEXT NOT NULL, name TEXT NOT NULL, "
        "PRIMARY KEY (package, name))"
    )
    c.execute("INSERT INTO schema_migrations VALUES ('velkgram.wishlist', '001_wishes.sql')")
    c.execute(
        "INSERT INTO wishes (name, required_terms, excluded_terms, max_price_cents, enabled, "
        "created_at, updated_at) VALUES ('w', '[]', '[]', 100, 1, 'x', 'x')"
    )
    c.commit()
    c.close()
    c2 = sqlite3.connect(tmp_path / "old.db")
    c2.row_factory = sqlite3.Row
    apply_migrations(c2, ["velkgram.shared", "velkgram.accounts", "velkgram.wishlist"])
    assert c2.execute("SELECT user_id FROM wishes").fetchone()[0] == 1
    assert "idx_wishes_user" in {r[1] for r in c2.execute("PRAGMA index_list(wishes)")}
    c2.close()


def test_usernames_are_unique_ignoring_case(tmp_path: Path) -> None:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, MIGRATION_PACKAGES)
    c.execute(
        "INSERT INTO users (username, password_hash, role, enabled, created_at) "
        "VALUES ('Ana', '', 'user', 1, 'x')"
    )
    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        c.execute(
            "INSERT INTO users (username, password_hash, role, enabled, created_at) "
            "VALUES ('ANA', '', 'user', 1, 'x')"
        )
    c.close()
