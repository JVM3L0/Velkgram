"""Shared helpers for web tests: a client over a freshly migrated temp DB."""

from pathlib import Path

from fastapi.testclient import TestClient

from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.apps.web.auth import hash_password
from velkgram.apps.web.main import create_app
from velkgram.shared.config import Settings
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

PASSWORD = "secret"


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "web.db",
        web_password_hash=hash_password(PASSWORD),
        web_secret_key="test-secret-key",
    )


def make_client(tmp_path: Path, *, login: bool = True) -> TestClient:
    settings = make_settings(tmp_path)
    conn = connect(settings.db_path)
    try:
        apply_migrations(conn, MIGRATION_PACKAGES)
    finally:
        conn.close()
    client = TestClient(create_app(settings), follow_redirects=False)
    if login:
        client.post("/login", data={"password": PASSWORD})
    return client
