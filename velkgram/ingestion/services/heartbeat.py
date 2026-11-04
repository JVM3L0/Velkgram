"""Heartbeat writer: counters live in memory, `beat` persists the full record."""

from velkgram.ingestion.domain.models import ConnectionState, Heartbeat
from velkgram.ingestion.ports.repository import MessageRepository
from velkgram.shared.ports import Clock


class HeartbeatWriter:
    def __init__(self, repo: MessageRepository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock
        self._messages = 0
        self._alerts = 0

    def count_message(self) -> None:
        self._messages += 1

    def count_alert(self) -> None:
        self._alerts += 1

    def beat(self, state: ConnectionState, reason: str | None = None) -> None:
        self._repo.write_heartbeat(
            Heartbeat(self._clock.now(), state, reason, self._messages, self._alerts)
        )
