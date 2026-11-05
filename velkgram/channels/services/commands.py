"""Channel write use cases."""

from dataclasses import replace

from velkgram.channels.domain.models import (
    Channel,
    ChannelStatus,
    InvalidChannel,
    parse_channel_ref,
)
from velkgram.channels.ports.repository import ChannelRepository
from velkgram.shared.ports import Clock


class ChannelCommands:
    def __init__(self, repo: ChannelRepository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock

    def add(self, raw_ref: str, silent_after_hours: int = 12) -> Channel:
        ref = parse_channel_ref(raw_ref)
        if self._repo.get_by_ref(ref) is not None:
            raise InvalidChannel("Canal já cadastrado")
        channel = Channel(
            None,
            ref,
            None,
            None,
            ChannelStatus.PENDING,
            None,
            True,
            silent_after_hours,
            self._clock.now(),
        )
        return self._repo.add(channel)

    def toggle(self, id: int, enabled: bool) -> None:
        self._repo.update(replace(self._require(id), enabled=enabled))

    def remove(self, id: int) -> None:
        self._repo.delete(id)

    def activate(self, id: int, telegram_id: int, name: str) -> None:
        current = self._require(id)
        self._repo.update(
            replace(
                current,
                telegram_id=telegram_id,
                name=name,
                status=ChannelStatus.ACTIVE,
                error=None,
            )
        )

    def fail(self, id: int, reason_pt: str) -> None:
        self._repo.update(replace(self._require(id), status=ChannelStatus.ERROR, error=reason_pt))

    def _require(self, id: int) -> Channel:
        current = self._repo.get(id)
        if current is None:
            raise InvalidChannel("Canal não encontrado")
        return current
