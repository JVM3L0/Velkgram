"""PublicChannels backed by the channels module's public API."""

from velkgram.channels import ChannelRepository


class ChannelsApiPublicChannels:
    def __init__(self, repo: ChannelRepository) -> None:
        self._repo = repo

    def public_channels(self) -> list[tuple[int, str]]:
        return [
            (c.telegram_id, c.ref.removeprefix("@"))
            for c in self._repo.list_enabled_active()
            if c.telegram_id is not None and c.ref.startswith("@")
        ]
