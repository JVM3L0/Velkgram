from datetime import UTC, datetime, timedelta

from velkgram.offers.domain.channel_page import is_telegram_cdn_url
from velkgram.offers.domain.image_files import StoredImage, images_to_delete

T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
LONG_AGO = T0 - timedelta(days=365)


def _img(n: int, size: int, age_days: int = 0) -> StoredImage:
    return StoredImage(-100, n, size, T0 - timedelta(days=age_days))


def _ids(images: list[StoredImage]) -> list[int]:
    return [i.message_id for i in images]


def test_nothing_is_deleted_while_the_total_fits_the_budget() -> None:
    images = [_img(1, 40), _img(2, 60)]
    assert images_to_delete(images, max_bytes=100, older_than=LONG_AGO) == []


def test_the_oldest_go_first_until_the_total_fits() -> None:
    images = [_img(1, 40, age_days=3), _img(2, 40, age_days=2), _img(3, 40, age_days=1)]
    assert _ids(images_to_delete(images, max_bytes=80, older_than=LONG_AGO)) == [1]
    assert _ids(images_to_delete(images, max_bytes=50, older_than=LONG_AGO)) == [1, 2]


def test_the_order_of_the_input_does_not_matter() -> None:
    images = [_img(3, 40, age_days=1), _img(1, 40, age_days=3), _img(2, 40, age_days=2)]
    assert _ids(images_to_delete(images, max_bytes=40, older_than=LONG_AGO)) == [1, 2]


def test_a_zero_budget_deletes_everything() -> None:
    assert _ids(images_to_delete([_img(1, 10), _img(2, 10)], 0, LONG_AGO)) == [1, 2]


def test_images_stored_before_the_cutoff_go_even_when_the_budget_is_not_hit() -> None:
    images = [_img(1, 10, age_days=100), _img(2, 10, age_days=1)]
    cutoff = T0 - timedelta(days=90)
    assert _ids(images_to_delete(images, max_bytes=10_000, older_than=cutoff)) == [1]


def test_expired_images_do_not_count_against_the_budget() -> None:
    # 1 is expired; once it is gone the other two fit, so only 1 is deleted.
    images = [_img(1, 50, age_days=100), _img(2, 50, age_days=2), _img(3, 50, age_days=1)]
    cutoff = T0 - timedelta(days=90)
    assert _ids(images_to_delete(images, max_bytes=100, older_than=cutoff)) == [1]


def test_only_telegrams_own_cdn_over_https_is_trusted() -> None:
    assert is_telegram_cdn_url("https://cdn1.telesco.pe/file/a.jpg")
    assert not is_telegram_cdn_url("http://cdn1.telesco.pe/file/a.jpg")
    assert not is_telegram_cdn_url("https://telesco.pe.evil.test/a.jpg")
    assert not is_telegram_cdn_url("https://m.media-amazon.com/images/a.jpg")
    assert not is_telegram_cdn_url(None)
