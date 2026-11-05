"""Match new and edited wishes against recent offers (retroactive runs)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from velkgram.offers.domain.build import wish_fingerprint
from velkgram.offers.domain.models import MatchSource, OfferMatch, RetroRun, RetroStatus
from velkgram.offers.ports.repository import OfferRepository
from velkgram.offers.ports.wishes import WishReader
from velkgram.shared.deals import WishView, matches
from velkgram.shared.events import WishlistChanged
from velkgram.shared.ports import Clock

log = logging.getLogger(__name__)


class RetroMatcher:
    def __init__(
        self,
        repo: OfferRepository,
        wishes: WishReader,
        clock: Clock,
        retention_days: int,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        chunk_size: int = 500,
    ) -> None:
        self._repo = repo
        self._wishes = wishes
        self._clock = clock
        self._retention_days = retention_days
        self._sleep = sleep
        self._chunk_size = chunk_size
        self._lock = asyncio.Lock()

    async def on_wishlist_changed(self, _e: WishlistChanged) -> None:
        async with self._lock:
            try:
                current = self._wishes.all()
                live_ids = {w.id for w in current}
                runs = {r.wish_id: r for r in self._repo.list_retro_runs()}
                for wish_id in runs.keys() - live_ids:
                    self._repo.delete_wish_data(wish_id)
                pending = [w for w in current if self._needs_run(w, runs.get(w.id))]
            except Exception:
                log.exception("retro_match_failed", extra={"wish_id": None})
                return
            for wish in pending:
                await self.run(wish)

    @staticmethod
    def _needs_run(wish: WishView, run: RetroRun | None) -> bool:
        if run is None or run.status is RetroStatus.running:
            return True
        return run.status is RetroStatus.done and run.fingerprint != wish_fingerprint(wish)

    async def run(self, wish: WishView) -> None:
        fingerprint = wish_fingerprint(wish)
        started = self._clock.now()
        try:
            self._repo.save_retro_run(
                RetroRun(wish.id, fingerprint, RetroStatus.running, started, None, None)
            )
            since = started - timedelta(days=self._retention_days)
            self._repo.delete_matches(wish.id, since)
            for chunk in self._repo.iter_offers_with_text(since, self._chunk_size):
                now = self._clock.now()
                found = [
                    OfferMatch(
                        wish_id=wish.id,
                        channel_id=o.channel_id,
                        message_id=o.message_id,
                        price_cents=o.price_cents,
                        posted_at=o.posted_at,
                        source=MatchSource.retro,
                        matched_at=now,
                    )
                    for o in chunk
                    if matches(wish, o.norm_text, o.price_cents)
                ]
                if found:
                    self._repo.add_matches(found)
                await self._sleep(0)
                if self._changed(wish.id, fingerprint):
                    return
            self._repo.save_retro_run(
                RetroRun(wish.id, fingerprint, RetroStatus.done, started, self._clock.now(), None)
            )
        except Exception as exc:
            log.exception("retro_match_failed", extra={"wish_id": wish.id})
            self._save_failed(wish.id, fingerprint, started, type(exc).__name__)

    def _changed(self, wish_id: int, fingerprint: str) -> bool:
        current = next((w for w in self._wishes.all() if w.id == wish_id), None)
        return current is None or wish_fingerprint(current) != fingerprint

    def _save_failed(self, wish_id: int, fingerprint: str, started: datetime, error: str) -> None:
        try:
            self._repo.save_retro_run(
                RetroRun(
                    wish_id,
                    fingerprint,
                    RetroStatus.failed,
                    started,
                    self._clock.now(),
                    error,
                )
            )
        except Exception:
            log.exception("retro_run_state_not_saved", extra={"wish_id": wish_id})
