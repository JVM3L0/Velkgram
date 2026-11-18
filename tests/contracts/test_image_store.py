from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.fakes.images import InMemoryImageStore
from velkgram.offers.adapters.fs.image_store import FsImageStore
from velkgram.offers.ports.image_files import ImageStore

T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "fs"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[ImageStore]:
    if request.param == "memory":
        yield InMemoryImageStore()
    else:
        yield FsImageStore(tmp_path / "images")


def test_put_then_get_returns_the_bytes(store: ImageStore) -> None:
    store.put(-100, 1, b"abc", T0)
    assert store.get(-100, 1) == b"abc"
    assert store.has(-100, 1)


def test_a_post_with_no_copy_has_none(store: ImageStore) -> None:
    assert store.get(-100, 1) is None
    assert not store.has(-100, 1)


def test_put_replaces_the_copy_of_the_same_post(store: ImageStore) -> None:
    store.put(-100, 1, b"old", T0)
    store.put(-100, 1, b"newer", T0 + timedelta(seconds=5))
    assert store.get(-100, 1) == b"newer"
    assert [(i.size, i.stored_at) for i in store.list()] == [(5, T0 + timedelta(seconds=5))]


def test_the_same_message_id_in_two_channels_is_two_copies(store: ImageStore) -> None:
    store.put(-100, 7, b"a", T0)
    store.put(-200, 7, b"bb", T0)
    assert store.get(-100, 7) == b"a"
    assert store.get(-200, 7) == b"bb"


def test_delete_forgets_the_copy_and_tolerates_a_missing_one(store: ImageStore) -> None:
    store.put(-100, 1, b"abc", T0)
    store.delete(-100, 1)
    store.delete(-100, 1)
    store.delete(-100, 99)
    assert store.get(-100, 1) is None
    assert store.list() == []


def test_list_gives_post_size_and_when_it_was_stored(store: ImageStore) -> None:
    store.put(-100, 1, b"abc", T0)
    store.put(-100, 2, b"de", T0 + timedelta(minutes=1))
    got = sorted((i.channel_id, i.message_id, i.size, i.stored_at) for i in store.list())
    assert got == [(-100, 1, 3, T0), (-100, 2, 2, T0 + timedelta(minutes=1))]
