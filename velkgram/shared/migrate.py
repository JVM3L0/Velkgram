"""Per-package SQL migrations tracked in `schema_migrations`."""

import sqlite3
from collections.abc import Sequence
from importlib.resources import files


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def apply_migrations(conn: sqlite3.Connection, packages: Sequence[str]) -> list[str]:
    """Apply pending `<package>/migrations/*.sql` in name order; return applied ids.

    `executescript` cannot take bound parameters and commits any open transaction, so each
    file is wrapped as one script: BEGIN IMMEDIATE; <sql>; <record>; COMMIT. On failure the
    open transaction is rolled back and the error re-raised.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "package TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (package, name))"
    )
    applied: list[str] = []
    for package in packages:
        directory = files(package) / "migrations"
        if not directory.is_dir():
            continue
        for entry in sorted(
            (e for e in directory.iterdir() if e.name.endswith(".sql")), key=lambda e: e.name
        ):
            done = conn.execute(
                "SELECT 1 FROM schema_migrations WHERE package = ? AND name = ?",
                (package, entry.name),
            ).fetchone()
            if done:
                continue
            record = (
                "INSERT INTO schema_migrations (package, name) "
                f"VALUES ({_quote(package)}, {_quote(entry.name)});"
            )
            script = f"BEGIN IMMEDIATE;\n{entry.read_text(encoding='utf-8')}\n{record}\nCOMMIT;"
            try:
                conn.executescript(script)
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            applied.append(f"{package}/{entry.name}")
    return applied
