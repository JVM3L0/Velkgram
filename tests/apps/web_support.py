"""Shared helpers for web tests: a client over a freshly migrated temp DB."""

from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.apps.web.auth import hash_password
from velkgram.apps.web.main import create_app
from velkgram.shared.config import Settings
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations
from velkgram.shared.ports import Clock

PASSWORD = "secret"


class FakeTestSender:
    """Stands in for the Telegram test alert: records chats, answers per chat or with `result`."""

    def __init__(self, result: str | None = None) -> None:
        self.chats: list[int] = []
        self.result = result
        self.results: dict[int, str | None] = {}  # per chat; wins over `result`

    async def send_one(self, chat_id: int) -> str | None:
        return (await self.send_many([chat_id]))[chat_id]

    async def send_many(self, chat_ids: Sequence[int]) -> dict[int, str | None]:
        self.chats.extend(chat_ids)
        return {c: self.results.get(c, self.result) for c in chat_ids}


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "web.db",
        web_password_hash=hash_password(PASSWORD),
        web_secret_key="test-secret-key",
    )


def make_client(tmp_path: Path, *, login: bool = True, clock: Clock | None = None) -> TestClient:
    settings = make_settings(tmp_path)
    conn = connect(settings.db_path)
    try:
        apply_migrations(conn, MIGRATION_PACKAGES)
    finally:
        conn.close()
    client = TestClient(
        create_app(settings, clock=clock, tester=FakeTestSender()), follow_redirects=False
    )
    if login:
        client.post("/login", data={"username": "admin", "password": PASSWORD})
    return client


def make_user_client(
    tmp_path: Path, username: str, password: str = "senha-forte-1", *, admin: bool = False
) -> TestClient:
    """A client logged in as `username`, created on the same database if it does not exist."""
    from velkgram.accounts import Role, UserCommands
    from velkgram.accounts.adapters.sqlite.repository import SqliteUserRepository
    from velkgram.apps.web.auth import verify_password
    from velkgram.shared.adapters.clock_system import SystemClock

    settings = make_settings(tmp_path)
    conn = connect(settings.db_path)
    try:
        apply_migrations(conn, MIGRATION_PACKAGES)
        repo = SqliteUserRepository(conn)
        if repo.get_by_username(username) is None:
            commands = UserCommands(repo, SystemClock(), hash_password, verify_password)
            commands.create(username, password, Role.ADMIN if admin else Role.USER)
    finally:
        conn.close()
    client = TestClient(create_app(settings, tester=FakeTestSender()), follow_redirects=False)
    response = client.post("/login", data={"username": username, "password": password})
    assert response.status_code == 303
    return client


def sender_of(client: TestClient) -> FakeTestSender:
    """The fake test-alert sender the app under test was built with."""
    from typing import cast

    from fastapi import FastAPI

    sender = cast(FastAPI, client.app).state.tester
    assert isinstance(sender, FakeTestSender)
    return sender
