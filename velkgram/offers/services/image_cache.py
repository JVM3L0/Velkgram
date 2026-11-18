"""Keep a small copy of each post picture, because Telegram's CDN links expire within days.

Off the alert path, like the rest of the post-image sync: a picture that cannot be fetched or
decoded costs one card its photo, nothing else.
"""

import logging
from collections.abc import Sequence
from datetime import timedelta

from velkgram.offers.domain.channel_page import PostImage
from velkgram.offers.domain.image_files import images_to_delete
from velkgram.offers.ports.image_files import ImageDownloader, ImageStore, Thumbnailer
from velkgram.shared.ports import Clock

log = logging.getLogger(__name__)

MAX_DOWNLOAD_BYTES = 1_000_000  # a post picture is tens of KB; anything bigger is not one


class ImageCache:
    def __init__(
        self,
        store: ImageStore,
        downloader: ImageDownloader,
        thumbnailer: Thumbnailer,
        clock: Clock,
        max_bytes: int,
        retention_days: int,
    ) -> None:
        self._store = store
        self._downloader = downloader
        self._thumbnailer = thumbnailer
        self._clock = clock
        self._max_bytes = max_bytes
        self._retention = timedelta(days=retention_days)

    def keep(self, channel_id: int, images: Sequence[PostImage]) -> int:
        """Copy the pictures not kept yet; return how many were. One failure skips only itself."""
        kept = 0
        for image in images:
            if self._store.has(channel_id, image.message_id):
                continue
            try:
                raw = self._downloader.fetch(image.url, MAX_DOWNLOAD_BYTES)
                small = self._thumbnailer.thumbnail(raw) if raw is not None else None
                if small is None:
                    continue
                self._store.put(channel_id, image.message_id, small, self._clock.now())
                kept += 1
            except Exception as e:
                # No link in the log: it is a signed CDN address.
                log.warning(
                    "post_image_cache_failed",
                    extra={
                        "channel_id": channel_id,
                        "message_id": image.message_id,
                        "error": type(e).__name__,
                    },
                )
        return kept

    def enforce_limits(self) -> int:
        """Delete what outlived the retention, then the oldest until the total fits the budget."""
        doomed = images_to_delete(
            self._store.list(), self._max_bytes, self._clock.now() - self._retention
        )
        for image in doomed:
            self._store.delete(image.channel_id, image.message_id)
        return len(doomed)
