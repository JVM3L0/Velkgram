import threading
from datetime import UTC, datetime

from tests.fakes.clock import FakeClock
from tests.fakes.repositories import (
    FakeChannelPages,
    FakePublicChannels,
    InMemoryPostImageRepository,
)
from velkgram.offers.domain.channel_page import PostImage
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
    assert pages.fetched == ["promotom"]
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
