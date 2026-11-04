"""Connection watcher: the only writer of the heartbeat connection state."""

import logging
from collections.abc import Awaitable, Callable

from velkgram.ingestion.services.heartbeat import HeartbeatWriter

log = logging.getLogger(__name__)


class ConnectionWatcher:
    def __init__(
        self,
        is_connected: Callable[[], bool],
        heartbeat: HeartbeatWriter,
        on_recovered: Callable[[], Awaitable[None]],
    ) -> None:
        self._is_connected = is_connected
        self._heartbeat = heartbeat
        self._on_recovered = on_recovered
        self._was_down = False

    async def tick(self) -> None:
        if not self._is_connected():
            self._was_down = True
            self._heartbeat.beat("reconnecting")
            return
        self._heartbeat.beat("connected")
        if self._was_down:
            try:
                await self._on_recovered()
            except Exception:
                log.exception("recovery_backfill_failed")
            else:
                self._was_down = False
