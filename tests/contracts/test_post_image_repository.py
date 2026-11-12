from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.fakes.repositories import InMemoryPostImageRepository
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.offers.adapters.sqlite.post_images import SqlitePostImageRepository
from velkgram.offers.domain.channel_page import PostImage
from velkgram.offers.ports.post_images import PostImageRepository
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def repo(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[PostImageRepository]:
    if request.param == "memory":
        yield InMemoryPostImageRepository()
        return
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, MIGRATION_PACKAGES)
    yield SqlitePostImageRepository(conn)
    conn.close()


def test_upsert_then_get_returns_the_url(repo: PostImageRepository) -> None:
    repo.upsert(-100, [PostImage(1, "https://cdn1.telesco.pe/a"), PostImage(2, "https://c/b")], T0)
    assert repo.get(-100, 1) == "https://cdn1.telesco.pe/a"
    assert repo.get(-100, 2) == "https://c/b"
    assert repo.get(-100, 3) is None
    assert repo.get(-200, 1) is None


def test_upsert_replaces_the_url_of_the_same_post(repo: PostImageRepository) -> None:
    repo.upsert(-100, [PostImage(1, "https://old")], T0)
    repo.upsert(-100, [PostImage(1, "https://new")], T0 + timedelta(minutes=5))
    assert repo.get(-100, 1) == "https://new"


def test_purge_before_drops_only_older_rows(repo: PostImageRepository) -> None:
    repo.upsert(-100, [PostImage(1, "https://old")], T0)
    repo.upsert(-100, [PostImage(2, "https://new")], T0 + timedelta(days=2))
    assert repo.purge_before(T0 + timedelta(days=1)) == 1
    assert repo.get(-100, 1) is None
    assert repo.get(-100, 2) == "https://new"
