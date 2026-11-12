"""Keep post image URLs fresh from the public web view of the watched channels.

Off the alert path: a slow or failing page costs a few cards their picture, nothing else.
"""

import logging
import threading
from collections.abc import Callable
from datetime import timedelta

from velkgram.offers.domain.channel_page import oldest_post_id, parse_channel_page
from velkgram.offers.ports.post_images import ChannelPages, PostImageRepository, PublicChannels
from velkgram.shared.ports import Clock

log = logging.getLogger(__name__)

SYNC_EVERY_S = 300.0
CATCH_UP_PAGES = 10  # 20 posts each, the window page included
CATCH_UP_PAUSE_S = 2.0
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
        self._oldest: dict[int, int] = {}  # channel -> oldest post id seen on its newest page

    def _store(self, channel_id: int, html: str) -> tuple[int, int | None]:
        found = parse_channel_page(html)
        self._images.upsert(channel_id, found, self._clock.now())
        return len(found), oldest_post_id(html)

    def sync_once(self) -> int:
        """Fetch every public channel's newest page and store its photos; return how many."""
        stored = 0
        self._images.purge_before(self._clock.now() - self._retention)
        for channel_id, username in self._channels.public_channels():
            try:
                html = self._pages.fetch(username)
                if html is None:
                    continue
                count, oldest = self._store(channel_id, html)
                stored += count
                if oldest is not None:
                    self._oldest[channel_id] = oldest
            except Exception as e:
                log.warning(
                    "post_images_failed", extra={"channel": username, "error": type(e).__name__}
                )
        return stored

    def catch_up(
        self,
        max_pages: int = CATCH_UP_PAGES,
        pause_s: float = CATCH_UP_PAUSE_S,
        wait: Callable[[float], bool] | None = None,
    ) -> int:
        """Walk back through older pages of each channel, for posts that left the newest page.

        Bounded and paused between pages, once per start. Returns how many images it stored.
        """
        sleep = wait or threading.Event().wait
        stored = 0
        for channel_id, username in self._channels.public_channels():
            try:
                stored += self._walk_back(channel_id, username, max_pages, pause_s, sleep)
            except Exception as e:
                log.warning(
                    "post_images_catch_up_failed",
                    extra={"channel": username, "error": type(e).__name__},
                )
        return stored

    def _walk_back(
        self,
        channel_id: int,
        username: str,
        max_pages: int,
        pause_s: float,
        sleep: Callable[[float], bool],
    ) -> int:
        cursor = self._oldest.get(channel_id)
        if cursor is None:
            html = self._pages.fetch(username)
            if html is None:
                return 0
            _, cursor = self._store(channel_id, html)
        stored = 0
        for _ in range(max_pages - 1):
            if cursor is None:
                break
            html = self._pages.fetch(username, before=cursor)
            if html is None:
                break
            count, oldest = self._store(channel_id, html)
            stored += count
            if oldest is None or oldest >= cursor:
                break  # nothing older, or no progress
            cursor = oldest
            if sleep(pause_s):
                break
        return stored

    def run(
        self,
        stop: threading.Event,
        interval_s: float = SYNC_EVERY_S,
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        sleep = wait or stop.wait
        first = True
        while not stop.is_set():
            try:
                self.sync_once()
                if first:
                    self.catch_up(wait=sleep)
                    first = False
            except Exception as e:
                log.warning("post_images_sync_failed", extra={"error": type(e).__name__})
            if sleep(interval_s):
                break
