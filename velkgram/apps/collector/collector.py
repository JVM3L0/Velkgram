"""Collector assembly: wires repositories, services and Telegram work together (spec §4.1, §6.1)."""

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable, Coroutine
from datetime import timedelta
from typing import Any

from velkgram.alerting import Alert, AlertMessage, Notifier
from velkgram.alerting.adapters.sqlite.repository import SqliteAlertRepository
from velkgram.alerting.adapters.wishlist_api import WishlistApiReader
from velkgram.alerting.domain.dedup import DedupCache
from velkgram.alerting.domain.format import message_link
from velkgram.alerting.services.evaluate import Evaluator
from velkgram.alerting.services.reprocess import reprocess_unprocessed
from velkgram.alerting.services.retry_failed import retry_failed, warm_cache
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.channels import ChannelCommands, ChannelStatus
from velkgram.channels.adapters.sqlite.repository import SqliteChannelRepository
from velkgram.ingestion import (
    ChannelResolutionError,
    ConnectionWatcher,
    HeartbeatWriter,
    Ingestor,
    TelegramDeferred,
    TelegramGateway,
    backfill_all,
    backfill_channel,
    gap_check,
)
from velkgram.ingestion.adapters.sqlite.repository import SqliteMessageRepository
from velkgram.shared.events import (
    ChannelsChanged,
    MessageEdited,
    MessageReceived,
    WishlistChanged,
)
from velkgram.shared.migrate import apply_migrations
from velkgram.shared.ports import Clock, EventBus
from velkgram.wishlist.adapters.sqlite.repository import SqliteWishRepository

log = logging.getLogger(__name__)

_DEDUP_WINDOW = timedelta(minutes=30)


class Collector:
    def __init__(
        self,
        conn: sqlite3.Connection,
        gateway: TelegramGateway,
        notifier: Notifier,
        clock: Clock,
        bus: EventBus,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._conn = conn
        self._gateway = gateway
        self._notifier = notifier
        self._clock = clock
        self._sleep = sleep
        self.bus = bus
        self.stopped = False
        self._enabled: frozenset[int] = frozenset()
        self._names: dict[int, str] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._resolve_lock = asyncio.Lock()

        self._wish_repo = SqliteWishRepository(conn)
        self._channel_repo = SqliteChannelRepository(conn)
        self._channels = ChannelCommands(self._channel_repo, clock)
        self._messages = SqliteMessageRepository(conn, clock)
        self._alerts = SqliteAlertRepository(conn)
        self._cache = DedupCache(_DEDUP_WINDOW)

        self.heartbeat = HeartbeatWriter(self._messages, clock)
        self.ingestor = Ingestor(
            self._messages,
            bus,
            clock,
            lambda: self._enabled,
            on_message=self.heartbeat.count_message,
        )
        self.evaluator = Evaluator(
            WishlistApiReader(self._wish_repo),
            self._alerts,
            self._cache,
            notifier,
            bus,
            clock,
            mark_processed=lambda ch, m: self._messages.mark_processed(ch, m, clock.now()),
            channel_names=lambda: self._names,
            on_alert_sent=self.heartbeat.count_alert,
            sleep=sleep,
        )
        self.watcher = ConnectionWatcher(
            gateway.is_connected, self.heartbeat, self.backfill_enabled
        )

    # --- lifecycle -------------------------------------------------------------------------

    async def start(self) -> None:
        apply_migrations(self._conn, MIGRATION_PACKAGES)
        self.reload_wishes()
        self._load_channels()
        warm_cache(self._alerts, self._cache, self._clock)
        await reprocess_unprocessed(
            self._messages.list_unprocessed_since, self.evaluator, self._clock
        )
        await self.resolve_pending()
        await self.backfill_enabled()
        self.bus.subscribe(MessageReceived, self.evaluator.on_received)
        self.bus.subscribe(MessageEdited, self.evaluator.on_edited)
        self.bus.subscribe(WishlistChanged, self._on_wishlist_changed)
        self.bus.subscribe(ChannelsChanged, self._on_channels_changed)

    async def wait_idle(self) -> None:
        while pending := [t for t in self._tasks if not t.done()]:
            await asyncio.gather(*pending, return_exceptions=True)
        await self.evaluator.wait_idle()

    async def fatal(self, reason: str) -> None:
        if self.stopped:
            return
        self.stopped = True
        self.ingestor.stop()
        try:  # alert first (spec §7): the heartbeat write must not delay or block it
            await self._notifier.notify_system(f"Velkgram parou: {reason}")
        except Exception:
            log.exception("fatal_notify_failed")
        try:
            self.heartbeat.beat("fatal", reason)
        except Exception:
            log.exception("fatal_heartbeat_failed")

    # --- state reload ----------------------------------------------------------------------

    def reload_wishes(self) -> None:
        """Wishes are read per message by the evaluator; nothing is cached to refresh."""
        log.info("wishes_reloaded")

    def _load_channels(self) -> None:
        enabled = self._channel_repo.list_enabled_active()
        self._enabled = frozenset(c.telegram_id for c in enabled if c.telegram_id is not None)
        self._names = {
            c.telegram_id: c.name or str(c.telegram_id)
            for c in self._channel_repo.list_all()
            if c.status is ChannelStatus.ACTIVE and c.telegram_id is not None
        }

    async def reload_channels(self) -> None:
        self._load_channels()
        await self.resolve_pending()

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _on_wishlist_changed(self, _e: WishlistChanged) -> None:
        self.reload_wishes()

    async def _on_channels_changed(self, _e: ChannelsChanged) -> None:
        self._load_channels()
        self._spawn(self._safe(self.resolve_pending(), "resolve_pending_failed"))

    @staticmethod
    async def _safe(coro: Awaitable[object], event: str) -> None:
        try:
            await coro
        except Exception:
            log.exception(event)

    # --- telegram work ---------------------------------------------------------------------

    async def resolve_pending(self) -> None:
        async with self._resolve_lock:
            for channel in self._channel_repo.list_pending():
                if channel.id is None:
                    continue
                try:
                    telegram_id = await self._resolve_one(channel.id, channel.ref)
                except TelegramDeferred as e:
                    log.warning(
                        "telegram_deferred", extra={"ref": channel.ref, "seconds": e.seconds}
                    )
                except ChannelResolutionError as e:
                    self._fail_channel(channel.id, str(e))
                except sqlite3.IntegrityError:
                    log.exception("channel_activate_conflict", extra={"ref": channel.ref})
                    self._fail_channel(channel.id, "Canal já cadastrado")
                except Exception:
                    log.exception("channel_activate_failed", extra={"ref": channel.ref})
                    self._fail_channel(channel.id, "Erro ao ativar o canal")
                else:  # the channel is active now; a backfill problem must not mark it failed
                    await self._safe(self._backfill_one(telegram_id), "new_channel_backfill_failed")

    async def _resolve_one(self, id: int, ref: str) -> int:
        resolved = await self._gateway.resolve_and_join(ref)
        self._channels.activate(id, resolved.telegram_id, resolved.title)
        self._load_channels()
        return resolved.telegram_id

    def _fail_channel(self, id: int, reason_pt: str) -> None:
        try:
            self._channels.fail(id, reason_pt)
        except Exception:
            log.exception("channel_fail_failed", extra={"channel_id": id})

    async def _backfill_one(self, channel_id: int) -> None:
        try:
            await backfill_channel(
                self._gateway, self.ingestor, self._messages, self._clock, channel_id
            )
        except TelegramDeferred as e:
            log.warning("telegram_deferred", extra={"channel_id": channel_id, "seconds": e.seconds})

    async def backfill_enabled(self) -> None:
        await backfill_all(
            self._gateway,
            self.ingestor,
            self._messages,
            self._clock,
            sorted(self._enabled),
            sleep=self._sleep,
        )

    # --- loop entry points (Task 17) -------------------------------------------------------

    async def run_gap_check(self) -> None:
        try:
            behind = await gap_check(self._gateway, self._messages, sorted(self._enabled))
            for channel_id in behind:
                await self._backfill_one(channel_id)
        except Exception:
            log.exception("gap_check_failed")

    async def run_retry_failed(self) -> None:
        try:
            await retry_failed(
                self._alerts,
                self._notifier,
                self._clock,
                self.build_message,
                sleep=self._sleep,
                on_alert_sent=self.heartbeat.count_alert,
            )
        except Exception:
            log.exception("retry_failed_error")

    async def housekeeping_tick(self) -> None:
        try:
            await self.watcher.tick()
            self._cache.prune(self._clock.now())
        except Exception:
            log.exception("housekeeping_failed")

    def build_message(self, alert: Alert) -> AlertMessage | None:
        m = self._messages.get(alert.channel_id, alert.message_id)
        wish = self._wish_repo.get(alert.wish_id)
        channel_name = self._names.get(alert.channel_id)
        if m is None or wish is None or channel_name is None:
            return None
        return AlertMessage(
            wish_name=wish.name,
            text=m.text,
            price_cents=alert.price_cents,
            channel_name=channel_name,
            link=message_link(m),
            delayed_minutes=alert.delayed_minutes,
        )
