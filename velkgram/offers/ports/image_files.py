"""Ports for keeping a small copy of each post picture, so it outlives Telegram's CDN link."""

from datetime import datetime
from typing import Protocol

from velkgram.offers.domain.image_files import StoredImage


class ImageStore(Protocol):
    def put(self, channel_id: int, message_id: int, data: bytes, now: datetime) -> None:
        """Keep `data` for the post, replacing any earlier copy. Never leaves a partial copy."""
        ...

    def get(self, channel_id: int, message_id: int) -> bytes | None: ...

    def has(self, channel_id: int, message_id: int) -> bool: ...

    def delete(self, channel_id: int, message_id: int) -> None:
        """Forget the copy; a post with none is not an error."""
        ...

    def list(self) -> list[StoredImage]: ...


class ImageDownloader(Protocol):
    def fetch(self, url: str, max_bytes: int) -> bytes | None:
        """The bytes behind `url`, or None when it is untrusted, missing, not an image or
        larger than `max_bytes`. Never raises for a bad answer."""
        ...


class Thumbnailer(Protocol):
    def thumbnail(self, data: bytes) -> bytes | None:
        """A small web-ready version of the image, or None when `data` is not a usable image."""
        ...
