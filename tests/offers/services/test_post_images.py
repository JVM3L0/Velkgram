import threading
from datetime import UTC, datetime

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.images import FakeImageDownloader, FakeThumbnailer, InMemoryImageStore
from tests.fakes.repositories import (
    FakeChannelPages,
    FakePublicChannels,
    InMemoryPostImageRepository,
)
from velkgram.offers.domain.channel_page import PostImage
from velkgram.offers.domain.image_files import StoredImage
from velkgram.offers.services.image_cache import ImageCache
from velkgram.offers.services.post_images import PostImageSync

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
CDN = "https://cdn1.telesco.pe/file/"


def _page(message_id: int, name: str) -> str:
    return (
        f'<div data-post="x/{message_id}"><a class="tgme_widget_message_photo_wrap" '
        f"style=\"background-image:url('{CDN}{name}.jpg')\"></a></div>"
    )


def _sync(
    channels: list[tuple[int, str]], pages: dict[str, str | Exception | None]
) -> tuple[PostImageSync, InMemoryPostImageRepository, FakeChannelPages]:
    repo = InMemoryPostImageRepository()
    fake_pages = FakeChannelPages(pages)
    sync = PostImageSync(FakePublicChannels(channels), fake_pages, repo, FakeClock(NOW))
    return sync, repo, fake_pages


def test_sync_stores_the_images_of_every_public_channel() -> None:
    sync, repo, pages = _sync(
        [(-100, "promotom"), (-200, "fumotom")],
        {"promotom": _page(7, "a"), "fumotom": _page(9, "b")},
    )
    assert sync.sync_once() == 2
    assert repo.get(-100, 7) == f"{CDN}a.jpg"
    assert repo.get(-200, 9) == f"{CDN}b.jpg"
    assert pages.fetched == ["promotom", "fumotom"]


def test_a_failing_channel_does_not_stop_the_others() -> None:
    sync, repo, _ = _sync(
        [(-100, "boom"), (-200, "gone"), (-300, "fumotom")],
        {"boom": RuntimeError("network"), "gone": None, "fumotom": _page(9, "b")},
    )
    assert sync.sync_once() == 1
    assert repo.get(-300, 9) == f"{CDN}b.jpg"


def test_sync_with_no_channels_does_nothing() -> None:
    sync, _, pages = _sync([], {})
    assert sync.sync_once() == 0
    assert pages.fetched == []


def test_run_syncs_then_waits_until_stopped() -> None:
    sync, repo, pages = _sync([(-100, "promotom")], {"promotom": _page(7, "a")})
    stop = threading.Event()
    waits: list[float] = []

    def wait(seconds: float) -> bool:
        waits.append(seconds)
        stop.set()
        return True

    sync.run(stop, interval_s=300.0, wait=wait)
    assert pages.fetched == ["promotom", "promotom:7"]  # the window, then one older page
    assert repo.get(-100, 7) == f"{CDN}a.jpg"
    assert waits == [300.0]


def test_sync_drops_images_older_than_the_retention() -> None:
    from datetime import timedelta

    sync, repo, _ = _sync([(-100, "promotom")], {"promotom": _page(7, "a")})
    repo.upsert(-100, [PostImage(1, f"{CDN}old.jpg")], NOW - timedelta(days=91))
    repo.upsert(-100, [PostImage(2, f"{CDN}young.jpg")], NOW - timedelta(days=10))
    sync.sync_once()
    assert repo.get(-100, 1) is None
    assert repo.get(-100, 2) == f"{CDN}young.jpg"
    assert repo.get(-100, 7) == f"{CDN}a.jpg"


def _posts(first: int, last: int) -> str:
    return "".join(_page(i, f"p{i}") for i in range(first, last + 1))


def test_catch_up_walks_back_through_older_pages_until_one_is_empty() -> None:
    sync, repo, pages = _sync(
        [(-100, "promotom")],
        {"promotom": _posts(50, 52), "promotom:50": _posts(47, 49), "promotom:47": ""},
    )
    sync.sync_once()
    assert sync.catch_up(max_pages=10, pause_s=0.0, wait=lambda _s: False) == 3
    assert pages.fetched == ["promotom", "promotom:50", "promotom:47"]
    assert repo.get(-100, 48) == f"{CDN}p48.jpg"


def test_catch_up_never_goes_past_the_page_cap() -> None:
    sync, _, pages = _sync(
        [(-100, "promotom")],
        {"promotom": _posts(50, 52), "promotom:50": _posts(47, 49), "promotom:47": _posts(44, 46)},
    )
    sync.catch_up(max_pages=2, pause_s=0.0, wait=lambda _s: False)
    assert pages.fetched == ["promotom", "promotom:50"]  # first page plus one older, then stop


def test_catch_up_stops_when_asked_to_stop_between_pages() -> None:
    sync, _, pages = _sync(
        [(-100, "promotom")],
        {"promotom": _posts(50, 52), "promotom:50": _posts(47, 49), "promotom:47": _posts(44, 46)},
    )
    sync.catch_up(max_pages=10, pause_s=1.0, wait=lambda _s: True)
    assert pages.fetched == ["promotom", "promotom:50"]


def test_catch_up_survives_a_failing_channel() -> None:
    sync, repo, _ = _sync(
        [(-100, "boom"), (-200, "fumotom")],
        {"boom": RuntimeError("x"), "fumotom": _posts(10, 11), "fumotom:10": ""},
    )
    sync.catch_up(max_pages=3, pause_s=0.0, wait=lambda _s: False)
    assert repo.get(-200, 10) == f"{CDN}p10.jpg"


# --- the local copy of each picture ---------------------------------------------------------


def _with_cache(
    channels: list[tuple[int, str]],
    pages: dict[str, str | Exception | None],
    bodies: dict[str, bytes],
    max_bytes: int = 10_000,
) -> tuple[PostImageSync, InMemoryImageStore, FakeImageDownloader]:
    store, downloader = InMemoryImageStore(), FakeImageDownloader(bodies)
    clock = FakeClock(NOW)
    cache = ImageCache(store, downloader, FakeThumbnailer(), clock, max_bytes, 90)
    sync = PostImageSync(
        FakePublicChannels(channels),
        FakeChannelPages(pages),
        InMemoryPostImageRepository(),
        clock,
        cache=cache,
    )
    return sync, store, downloader


def test_sync_keeps_a_copy_of_each_picture_it_finds() -> None:
    sync, store, _ = _with_cache(
        [(-100, "promotom")], {"promotom": _page(7, "a")}, {f"{CDN}a.jpg": b"raw"}
    )
    sync.sync_once()
    assert store.get(-100, 7) == b"thumb:raw"


def test_the_next_sync_does_not_download_a_kept_picture_again() -> None:
    sync, _, downloader = _with_cache(
        [(-100, "promotom")], {"promotom": _page(7, "a")}, {f"{CDN}a.jpg": b"raw"}
    )
    sync.sync_once()
    sync.sync_once()
    assert downloader.calls == [f"{CDN}a.jpg"]


def test_catch_up_keeps_the_pictures_of_older_pages_too() -> None:
    page = _posts(1, 3)
    sync, store, _ = _with_cache(
        [(-100, "promotom")],
        {"promotom": page},
        {f"{CDN}p{n}.jpg": b"raw" for n in (1, 2, 3)},
    )
    sync.catch_up(wait=lambda _s: False)
    assert {i.message_id for i in store.list()} == {1, 2, 3}


def test_sync_enforces_the_budget_after_keeping() -> None:
    sync, store, _ = _with_cache(
        [(-100, "promotom")],
        {"promotom": _posts(1, 3)},
        {f"{CDN}p{n}.jpg": b"x" * 10 for n in (1, 2, 3)},
        max_bytes=32,
    )
    sync.sync_once()
    assert sum(i.size for i in store.list()) <= 32
    assert len(store.list()) == 2


class _UnlistableStore(InMemoryImageStore):
    def list(self) -> list[StoredImage]:
        raise OSError("volume gone")


def test_a_broken_store_does_not_stop_the_url_sync(caplog: pytest.LogCaptureFixture) -> None:
    clock = FakeClock(NOW)
    cache = ImageCache(
        _UnlistableStore(), FakeImageDownloader(), FakeThumbnailer(), clock, 10_000, 90
    )
    sync = PostImageSync(
        FakePublicChannels([(-100, "promotom")]),
        FakeChannelPages({"promotom": _page(7, "a")}),
        InMemoryPostImageRepository(),
        clock,
        cache=cache,
    )
    with caplog.at_level("WARNING"):
        assert sync.sync_once() == 1
    assert any(r.message == "post_image_cache_enforce_failed" for r in caplog.records)
