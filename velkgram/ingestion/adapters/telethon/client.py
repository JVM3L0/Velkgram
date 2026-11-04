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
