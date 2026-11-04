"""Connection watcher: the only writer of the heartbeat connection state."""

from collections.abc import Awaitable, Callable

from velkgram.ingestion.services.heartbeat import HeartbeatWriter


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
        if self._was_down:
            self._was_down = False
            await self._on_recovered()
        self._heartbeat.beat("connected")
