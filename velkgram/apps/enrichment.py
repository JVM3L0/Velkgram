"""Runs the link enricher and the post-image sync on worker threads of the collector process.

The collector publishes `OfferCreated` once a live offer is stored; its handler calls `wake`, so
a new link is followed at once instead of waiting for the enricher's periodic discovery. The
database stays the work queue (retries, backoff and restarts depend on it); `wake` is only the
doorbell. Each thread opens its own SQLite connection.
"""

import logging
import threading
from collections.abc import Callable

from velkgram.channels.adapters.sqlite.repository import SqliteChannelRepository
from velkgram.offers import LinkEnricher
from velkgram.offers.adapters.channels_api import ChannelsApiPublicChannels
from velkgram.offers.adapters.http.channel_pages import HttpxChannelPages
from velkgram.offers.adapters.http.fetcher import HttpxFetcher, configure_fetch_logging
from velkgram.offers.adapters.sqlite.links import SqliteLinkRepository
from velkgram.offers.adapters.sqlite.post_images import SqlitePostImageRepository
from velkgram.offers.ports.fetcher import Fetcher
from velkgram.offers.ports.post_images import ChannelPages
from velkgram.offers.services.post_images import PostImageSync
from velkgram.shared.adapters.clock_system import SystemClock
from velkgram.shared.config import Settings
from velkgram.shared.db import connect

log = logging.getLogger(__name__)

RESTART_DELAY_S = 5.0
JOIN_TIMEOUT_S = 20.0


def run_post_images(
    settings: Settings, stop: threading.Event, make_pages: Callable[[], ChannelPages]
) -> None:
    """Keep post image URLs fresh; its own connection, since it runs on its own thread."""
    conn = connect(settings.db_path)
    try:
        PostImageSync(
            ChannelsApiPublicChannels(SqliteChannelRepository(conn)),
            make_pages(),
            SqlitePostImageRepository(conn),
            SystemClock(),
            settings.retention_days,
        ).run(stop)
    finally:
        conn.close()


class EnricherHost:
    def __init__(
        self,
        settings: Settings,
        make_fetcher: Callable[[], Fetcher] = HttpxFetcher,
        make_pages: Callable[[], ChannelPages] = HttpxChannelPages,
        restart_delay_s: float = RESTART_DELAY_S,
    ) -> None:
        self._settings = settings
        self._make_fetcher = make_fetcher
        self._make_pages = make_pages
        self._restart_delay_s = restart_delay_s
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        configure_fetch_logging()
        workers: dict[str, Callable[[], None]] = {
            "link-enricher": self._enrich,
            "post-images": lambda: run_post_images(self._settings, self._stop, self._make_pages),
        }
        for name, work in workers.items():
            thread = threading.Thread(
                target=self._supervised, args=(name, work), name=name, daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def wake(self) -> None:
        """A live offer with a link was stored. Safe from any thread."""
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        for thread in self._threads:
            thread.join(timeout=JOIN_TIMEOUT_S)
        self._threads.clear()

    def _enrich(self) -> None:
        conn = connect(self._settings.db_path)
        try:
            enricher = LinkEnricher(
                SqliteLinkRepository(conn), self._make_fetcher(), SystemClock(), wake=self._wake
            )
            enricher.run(self._stop)
        finally:
            conn.close()

    def _supervised(self, name: str, work: Callable[[], None]) -> None:
        """Run `work` until stopped; a crash is logged and the worker starts again."""
        while not self._stop.is_set():
            try:
                work()
                return
            except Exception:
                log.exception("enricher_crashed", extra={"worker": name})
            if self._stop.wait(self._restart_delay_s):
                return
