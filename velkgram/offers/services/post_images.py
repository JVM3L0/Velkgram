"""Keep post image URLs fresh from the public web view of the watched channels.

Off the alert path: a slow or failing page costs a few cards their picture, nothing else.
"""

import logging
import threading
from collections.abc import Callable
from datetime import timedelta

from velkgram.offers.domain.channel_page import parse_channel_page
from velkgram.offers.ports.post_images import ChannelPages, PostImageRepository, PublicChannels
from velkgram.shared.ports import Clock

log = logging.getLogger(__name__)

SYNC_EVERY_S = 300.0
RETENTION_DAYS = 90


class PostImageSync:
    def __init__(
        self,
        channels: PublicChannels,
        pages: ChannelPages,
        images: PostImageRepository,
        clock: Clock,
        retention_days: int = RETENTION_DAYS,
    ) -> None:
        self._retention = timedelta(days=retention_days)
        self._channels = channels
        self._pages = pages
        self._images = images
        self._clock = clock

    def sync_once(self) -> int:
        """Fetch every public channel's page and store its photos; return how many were stored."""
        stored = 0
        self._images.purge_before(self._clock.now() - self._retention)
        for channel_id, username in self._channels.public_channels():
            try:
                html = self._pages.fetch(username)
                if html is None:
                    continue
                found = parse_channel_page(html)
                self._images.upsert(channel_id, found, self._clock.now())
                stored += len(found)
            except Exception as e:
                log.warning(
                    "post_images_failed", extra={"channel": username, "error": type(e).__name__}
                )
        return stored

    def run(
        self,
        stop: threading.Event,
        interval_s: float = SYNC_EVERY_S,
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        sleep = wait or stop.wait
        while not stop.is_set():
            try:
                self.sync_once()
            except Exception as e:
                log.warning("post_images_sync_failed", extra={"error": type(e).__name__})
            if sleep(interval_s):
                break
