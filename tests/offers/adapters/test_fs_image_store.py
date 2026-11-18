import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from velkgram.offers.adapters.fs.image_store import FsImageStore

T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def test_the_directory_is_created_on_the_first_copy_not_before(tmp_path: Path) -> None:
    root = tmp_path / "images"
    store = FsImageStore(root)
    assert store.list() == []
    assert not root.exists()
    store.put(-100, 1, b"x", T0)
    assert root.is_dir()


def test_a_copy_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    store = FsImageStore(tmp_path)
    store.put(-100, 1, b"x", T0)
    assert [p.name for p in tmp_path.iterdir()] == ["-100_1.webp"]


def test_a_failed_write_leaves_neither_a_copy_nor_a_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    store = FsImageStore(tmp_path)
    with pytest.raises(OSError, match="disk full"):
        store.put(-100, 1, b"x", T0)
    assert list(tmp_path.iterdir()) == []


def test_files_that_are_not_copies_are_not_listed(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "abc_def.webp").write_text("x")
    FsImageStore(tmp_path).put(-100, 1, b"x", T0)
    assert [(i.channel_id, i.message_id) for i in FsImageStore(tmp_path).list()] == [(-100, 1)]


def test_a_stale_temporary_file_is_cleaned_up_and_a_fresh_one_is_left(tmp_path: Path) -> None:
    stale, fresh = tmp_path / ".tmp-old", tmp_path / ".tmp-new"
    stale.write_bytes(b"x")
    fresh.write_bytes(b"x")
    two_hours_ago = time.time() - 7200
    os.utime(stale, (two_hours_ago, two_hours_ago))
    FsImageStore(tmp_path).list()
    assert not stale.exists()
    assert fresh.exists()
