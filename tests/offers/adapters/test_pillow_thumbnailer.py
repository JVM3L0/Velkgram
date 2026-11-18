import io

import pytest
from PIL import Image

from velkgram.offers.adapters.image import pillow_thumbnailer
from velkgram.offers.adapters.image.pillow_thumbnailer import THUMB_PX, PillowThumbnailer


def _jpeg(width: int, height: int) -> bytes:
    # Noise-like content, so the original is not tiny to begin with.
    image = Image.effect_noise((width, height), 80).convert("RGB")
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90)
    return out.getvalue()


def _decoded(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def test_a_large_jpeg_becomes_a_small_webp_within_the_thumbnail_box() -> None:
    original = _jpeg(1280, 960)
    small = PillowThumbnailer().thumbnail(original)
    assert small is not None
    image = _decoded(small)
    assert image.format == "WEBP"
    assert max(image.size) == THUMB_PX
    assert image.size == (320, 240)  # the aspect ratio is kept
    assert len(small) < len(original) / 3


def test_a_picture_already_small_is_not_enlarged() -> None:
    small = PillowThumbnailer().thumbnail(_jpeg(100, 80))
    assert small is not None
    assert _decoded(small).size == (100, 80)


def test_a_png_with_transparency_keeps_it() -> None:
    image = Image.new("RGBA", (50, 50), (255, 0, 0, 0))
    out = io.BytesIO()
    image.save(out, "PNG")
    small = PillowThumbnailer().thumbnail(out.getvalue())
    assert small is not None
    assert _decoded(small).mode == "RGBA"


@pytest.mark.parametrize("data", [b"", b"not an image", b"\xff\xd8\xff\xe0" + b"\x00" * 20])
def test_bytes_that_are_not_a_usable_image_give_nothing(data: bytes) -> None:
    assert PillowThumbnailer().thumbnail(data) is None


def test_a_truncated_jpeg_gives_nothing() -> None:
    assert PillowThumbnailer().thumbnail(_jpeg(640, 480)[:200]) is None


def test_an_image_with_too_many_pixels_is_refused_before_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pillow_thumbnailer, "MAX_PIXELS", 400)
    assert PillowThumbnailer().thumbnail(_jpeg(20, 20)) is not None
    assert PillowThumbnailer().thumbnail(_jpeg(21, 20)) is None
