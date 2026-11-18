from datetime import UTC, datetime, timedelta

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.images import FakeImageDownloader, FakeThumbnailer, InMemoryImageStore
from velkgram.offers.domain.channel_page import PostImage
from velkgram.offers.services.image_cache import MAX_DOWNLOAD_BYTES, ImageCache

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
A, B, C = "https://cdn1.telesco.pe/a", "https://cdn1.telesco.pe/b", "https://cdn1.telesco.pe/c"


def _cache(
    bodies: dict[str, bytes], max_bytes: int = 10_000, retention_days: int = 90
) -> tuple[ImageCache, InMemoryImageStore, FakeImageDownloader, FakeThumbnailer, FakeClock]:
    store, downloader, thumbs = InMemoryImageStore(), FakeImageDownloader(bodies), FakeThumbnailer()
    clock = FakeClock(NOW)
    cache = ImageCache(store, downloader, thumbs, clock, max_bytes, retention_days)
    return cache, store, downloader, thumbs, clock


def test_each_new_picture_is_downloaded_shrunk_and_kept() -> None:
    cache, store, _, _, _ = _cache({A: b"raw-a", B: b"raw-b"})
    assert cache.keep(-100, [PostImage(1, A), PostImage(2, B)]) == 2
    assert store.get(-100, 1) == b"thumb:raw-a"
    assert store.get(-100, 2) == b"thumb:raw-b"


def test_a_picture_already_kept_is_not_downloaded_again() -> None:
    cache, _, downloader, thumbs, _ = _cache({A: b"raw-a"})
    cache.keep(-100, [PostImage(1, A)])
    assert cache.keep(-100, [PostImage(1, A)]) == 0
    assert downloader.calls == [A]
    assert thumbs.calls == 1


def test_a_changed_link_for_a_kept_post_is_still_not_downloaded() -> None:
    cache, _, downloader, _, _ = _cache({A: b"raw-a", B: b"raw-b"})
    cache.keep(-100, [PostImage(1, A)])
    cache.keep(-100, [PostImage(1, B)])  # Telegram rotates the link, the picture is the same
    assert downloader.calls == [A]


def test_the_download_is_capped() -> None:
    cache, store, _, _, _ = _cache({A: b"x" * (MAX_DOWNLOAD_BYTES + 1)})
    assert cache.keep(-100, [PostImage(1, A)]) == 0
    assert not store.has(-100, 1)


def test_a_failing_download_does_not_stop_the_rest() -> None:
    cache, store, downloader, _, _ = _cache({A: b"raw-a", C: b"raw-c"})
    downloader.failing.add(A)
    assert cache.keep(-100, [PostImage(1, A), PostImage(2, B), PostImage(3, C)]) == 1
    assert [store.has(-100, n) for n in (1, 2, 3)] == [False, False, True]


def test_a_picture_that_cannot_be_decoded_is_skipped() -> None:
    cache, store, _, _, _ = _cache({A: b"bad-image", B: b"raw-b"})
    assert cache.keep(-100, [PostImage(1, A), PostImage(2, B)]) == 1
    assert not store.has(-100, 1)


def test_a_failure_is_logged_without_the_link(caplog: pytest.LogCaptureFixture) -> None:
    cache, _, downloader, _, _ = _cache({A: b"raw-a"})
    downloader.failing.add(A)
    with caplog.at_level("WARNING"):
        cache.keep(-100, [PostImage(1, A)])
    record = next(r for r in caplog.records if r.message == "post_image_cache_failed")
    extra = record.__dict__
    assert (extra["channel_id"], extra["message_id"], extra["error"]) == (-100, 1, "RuntimeError")
    assert A not in caplog.text


def test_enforcing_deletes_the_oldest_pictures_over_the_budget() -> None:
    cache, store, _, _, clock = _cache({A: b"a" * 10, B: b"b" * 10, C: b"c" * 10}, max_bytes=40)
    for n, url in enumerate((A, B, C), start=1):
        cache.keep(-100, [PostImage(n, url)])
        clock.advance(60)
    # each copy is 6 + 10 bytes; 48 in all against a budget of 40: the oldest goes
    assert cache.enforce_limits() == 1
    assert [i.message_id for i in store.list()] == [2, 3]


def test_enforcing_deletes_what_is_older_than_the_retention() -> None:
    cache, store, _, _, clock = _cache({A: b"raw-a", B: b"raw-b"}, retention_days=30)
    cache.keep(-100, [PostImage(1, A)])
    clock.advance(31 * 86400)
    cache.keep(-100, [PostImage(2, B)])
    assert cache.enforce_limits() == 1
    assert [i.message_id for i in store.list()] == [2]


def test_enforcing_with_everything_inside_the_limits_deletes_nothing() -> None:
    cache, store, _, _, _ = _cache({A: b"raw-a"})
    cache.keep(-100, [PostImage(1, A)])
    assert cache.enforce_limits() == 0
    assert store.has(-100, 1)


def test_the_timestamp_of_a_copy_is_when_it_was_kept() -> None:
    cache, store, _, _, clock = _cache({A: b"raw-a"})
    clock.advance(5)
    cache.keep(-100, [PostImage(1, A)])
    assert store.list()[0].stored_at == NOW + timedelta(seconds=5)
