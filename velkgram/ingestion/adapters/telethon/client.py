"""Telethon client factory and auth-failure classification."""

from telethon import TelegramClient, errors
from telethon.sessions import StringSession

from velkgram.shared.config import Settings

_AUTH_FATAL = (
    errors.AuthKeyDuplicatedError,
    errors.AuthKeyUnregisteredError,
    errors.UserDeactivatedBanError,
    errors.SessionRevokedError,
)


def build_client(settings: Settings) -> TelegramClient:
    """Build an unconnected client. After `connect()` the caller awaits `client.catch_up()`.

    A StringSession keeps no update state across restarts, so backfill is the real recovery path.
    """
    if settings.tg_api_id is None or settings.tg_api_hash is None:
        raise ValueError("TG_API_ID and TG_API_HASH are required")
    return TelegramClient(
        StringSession(settings.tg_session or ""),
        settings.tg_api_id,
        settings.tg_api_hash,
        flood_sleep_threshold=60,
    )


def is_auth_fatal(exc: BaseException) -> bool:
    return isinstance(exc, _AUTH_FATAL)


class TelethonBotClient:
    """Bot-token session. Satisfies alerting's `BotClient` structurally (no alerting import)."""

    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    async def start(self, bot_token: str) -> None:
        await self._client.start(bot_token=bot_token)  # type: ignore[misc]

    async def send_message(self, chat_id: int, text: str, *, link_preview: bool) -> None:
        await self._client.send_message(chat_id, text, link_preview=link_preview)  # type: ignore[misc]

    async def disconnect(self) -> None:
        await self._client.disconnect()  # type: ignore[misc]


def build_bot_client(settings: Settings) -> TelethonBotClient:
    """A separate in-memory session for the alert bot; never touches the user session."""
    if settings.tg_api_id is None or settings.tg_api_hash is None:
        raise ValueError("TG_API_ID and TG_API_HASH are required")
    return TelethonBotClient(
        TelegramClient(
            StringSession(""),
            settings.tg_api_id,
            settings.tg_api_hash,
            flood_sleep_threshold=0,
        )
    )
