"""Link enrichment loop: follow offer links off the hot path and store what they reveal."""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta

from velkgram.offers.domain.links import (
    FetchOutcome,
    LinkInfo,
    budget_for,
    fetch_plan,
    resolve,
    resolve_url_only,
)
from velkgram.offers.domain.urls import host_of, strip_query
from velkgram.offers.ports.fetcher import Fetcher, HostPaused
from velkgram.offers.ports.links import LinkRepository, LinkRow
from velkgram.shared.ports import Clock

log = logging.getLogger(__name__)

DISCOVER_BATCH = 50
DISCOVER_EVERY_S = 60.0
HOST_GAP_S = 2.0
IDLE_MAX_S = 10.0
STOP_POLL_S = 0.5
HEARTBEAT_EVERY_S = 60.0
PAUSE = timedelta(minutes=30)
BLOCK_RETRY = timedelta(hours=24)
MAX_BLOCKS = 2
ERROR_BACKOFF = (timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=6))


class LinkEnricher:
    def __init__(
        self,
        links: LinkRepository,
        fetcher: Fetcher,
        clock: Clock,
        wait: Callable[[float], bool] | None = None,
        wake: threading.Event | None = None,
    ) -> None:
        self._links = links
        self._fetcher = fetcher
        self._clock = clock
        self._custom_wait = wait  # None: `run` sleeps on its stop event, so SIGTERM interrupts
        self._wait: Callable[[float], bool] = wait or threading.Event().wait
        self._wake = wake or threading.Event()  # set by `wake`: new work, stop sleeping
        self._stop: threading.Event | None = None
        self._paused: dict[str, datetime] = {}
        self._pause_hit: datetime | None = None  # end of the pause that stopped the last fetch
        self._last_request: dict[str, datetime] = {}
        self._last_discover_at: datetime | None = None
        self._last_discovered = 0

    # --- discovery and scheduling -------------------------------------------------------

    def wake(self) -> None:
        """New links may exist: end the idle sleep and discover now. Safe from any thread."""
        self._wake.set()

    def _sleep(self, seconds: float) -> bool:
        """The idle sleep: ends early on `wake`; True when the loop should stop."""
        if self._custom_wait is not None:
            return self._custom_wait(seconds)
        deadline = time.monotonic() + seconds
        while True:
            stopping = self._stop is not None and self._stop.is_set()
            left = deadline - time.monotonic()
            if stopping or left <= 0:
                return stopping
            # Two events cannot be awaited at once: a stop is noticed within STOP_POLL_S.
            if self._wake.wait(min(left, STOP_POLL_S)):
                return self._stop is not None and self._stop.is_set()

    def _paused_hosts(self, now: datetime) -> frozenset[str]:
        self._paused = {h: until for h, until in self._paused.items() if until > now}
        return frozenset(self._paused)

    def _unavailable_hosts(self, now: datetime) -> frozenset[str]:
        """Paused hosts plus hosts inside their gap: their rows wait, other hosts go on."""
        return self._paused_hosts(now) | frozenset(self._cooling_hosts(now))

    def _cooling_hosts(self, now: datetime) -> dict[str, float]:
        """Hosts still inside their request gap, with the seconds left in it."""
        left = {
            host: HOST_GAP_S - (now - last).total_seconds()
            for host, last in self._last_request.items()
        }
        return {host: secs for host, secs in left.items() if secs > 0}

    def _cooldown_wait(self, now: datetime) -> float | None:
        """Seconds until a host's gap ends, when only such hosts hold the due rows back."""
        cooling = self._cooling_hosts(now)
        if not cooling:
            return None
        earliest = self._links.earliest_next_try(now, self._paused_hosts(now))
        if earliest is None or earliest > now:
            return None
        return min(cooling.values())

    def _discover_if_due(self, now: datetime) -> None:
        woken = self._wake.is_set()
        self._wake.clear()  # before the scan: a row stored after it re-wakes the next sleep
        due = (
            woken
            or self._last_discover_at is None
            or self._last_discovered >= DISCOVER_BATCH
            or (now - self._last_discover_at).total_seconds() >= DISCOVER_EVERY_S
        )
        if due:
            self._last_discovered = self._links.discover(DISCOVER_BATCH)
            self._last_discover_at = now

    def step(self) -> bool:
        """Discover when due, then process one due link; True when a link was processed."""
        now = self._clock.now()
        self._discover_if_due(now)
        row = self._links.next_due(now, self._unavailable_hosts(now))
        if row is None:
            return False
        self._process(row)
        return True

    def run(self, stop: threading.Event, limit: int | None = None, until_idle: bool = False) -> int:
        self._wait = self._custom_wait or stop.wait
        self._stop = stop
        processed = 0
        last_beat: datetime | None = None
        while not stop.is_set() and (limit is None or processed < limit):
            if self.step():
                processed += 1
                last_beat = self._beat()
                continue
            now = self._clock.now()
            cooldown = self._cooldown_wait(now)
            if cooldown is not None:
                if self._wait(cooldown):
                    break
                continue
            if until_idle:
                # Idle, but the periodic discovery may not have looked since the last batch.
                self._last_discovered = self._links.discover(DISCOVER_BATCH)
                self._last_discover_at = now
                if self._last_discovered == 0:
                    break
                continue
            if last_beat is None or (now - last_beat).total_seconds() >= HEARTBEAT_EVERY_S:
                last_beat = self._beat()
            if self._sleep(self._idle_delay(now)):
                break
        return processed

    def _beat(self) -> datetime:
        now = self._clock.now()
        self._links.write_heartbeat(now)
        return now

    def _idle_delay(self, now: datetime) -> float:
        # Hosts in their request gap still count: `run` waits those out before it idles, so a
        # row left here is not due yet and the sleep must end when it is.
        earliest = self._links.earliest_next_try(now, self._paused_hosts(now))
        if earliest is None:
            return IDLE_MAX_S
        return min(IDLE_MAX_S, max(0.0, (earliest - now).total_seconds()))

    # --- one link -----------------------------------------------------------------------

    def _throttle(self, url: str) -> None:
        host = host_of(url)
        now = self._clock.now()
        if host in self._paused_hosts(now):
            self._pause_hit = self._paused[host]
            raise HostPaused(host)
        last = self._last_request.get(host)
        if last is not None:
            gap = HOST_GAP_S - (now - last).total_seconds()
            if gap > 0:
                if self._wait(gap):
                    raise HostPaused(host)  # stopping: leave the row untouched
                now += timedelta(seconds=gap)
        self._last_request[host] = now

    def _process(self, row: LinkRow) -> None:
        host = host_of(row.url)
        try:
            self._enrich(row)
        except Exception as e:
            log.warning("link_enrich_failed", extra={"host": host, "error": type(e).__name__})
            try:
                self._links.save(self._after_error(row, self._clock.now()), fix_store=False)
            except Exception as e2:
                log.warning("link_enrich_failed", extra={"host": host, "error": type(e2).__name__})

    def _enrich(self, row: LinkRow) -> None:
        now = self._clock.now()
        host = host_of(row.url)
        reused = self._reuse(row, now)
        if reused is not None:
            self._links.save(reused, fix_store=True)
            log.info("link_enriched", extra={"host": host, "status": "reused", "kind": "product"})
            return
        self._pause_hit = None
        outcome = self._fetcher.fetch(
            row.url, fetch_plan(row.url), before_request=self._throttle, budget_for=budget_for
        )
        if outcome.status == "paused":
            self._defer_until_unpaused(row)
            return
        info = resolve(row.url, outcome)
        now = self._clock.now()
        saved = self._apply(row, outcome, info, now)
        self._links.save(saved, fix_store=info.store is not None)
        log.info("link_enriched", extra={"host": host, "status": outcome.status, "kind": info.kind})

    def _defer_until_unpaused(self, row: LinkRow) -> None:
        """A later hop's host is paused: no attempt, but do not re-pick the row until it ends.

        A stop during the throttle wait also reads as paused; that leaves the row untouched.
        """
        until = self._pause_hit
        if until is None:
            return
        self._links.save(replace(row, next_try_at=until), fix_store=False)

    def _reuse(self, row: LinkRow, now: datetime) -> LinkRow | None:
        info = resolve_url_only(row.url)
        if info is None or info.store is None or info.product_id is None:
            return None
        known = self._links.known_product(info.store, info.product_id)
        if known is None:
            return None
        return replace(
            row,
            final_url=strip_query(row.url),
            store=info.store,
            product_id=info.product_id,
            title=known[0],
            image_url=known[1],
            kind="product",
            status="done",
            next_try_at=None,
            fetched_at=now,
        )

    def _apply(self, row: LinkRow, outcome: FetchOutcome, info: LinkInfo, now: datetime) -> LinkRow:
        status = outcome.status
        base = replace(
            row,
            final_url=strip_query(outcome.final_url),
            store=info.store,
            product_id=info.product_id,
            title=info.title,
            image_url=info.image_url,
            kind=info.kind,
            fetched_at=now,
        )
        if status == "error" or (isinstance(status, int) and status >= 500):
            return self._after_error(base, now)  # keeps the store and id already known
        if info.kind == "product":
            return replace(base, status="done", next_try_at=None)
        if status in (403, 429):
            self._paused[outcome.answered_by] = now + PAUSE
            blocks = row.blocks + 1
            if blocks >= MAX_BLOCKS:
                return replace(base, blocks=blocks, status="failed", next_try_at=None)
            return replace(base, blocks=blocks, status="blocked", next_try_at=now + BLOCK_RETRY)
        return replace(base, status="done", next_try_at=None)

    @staticmethod
    def _after_error(row: LinkRow, now: datetime) -> LinkRow:
        attempts = row.attempts + 1
        if attempts > len(ERROR_BACKOFF):
            return replace(row, attempts=attempts, status="failed", next_try_at=None)
        return replace(
            row, attempts=attempts, status="pending", next_try_at=now + ERROR_BACKOFF[attempts - 1]
        )
