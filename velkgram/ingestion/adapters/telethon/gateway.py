"""TelegramGateway implementation over Telethon."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from telethon import TelegramClient, errors, utils
from telethon.tl import functions, types

from velkgram.ingestion.adapters.telethon.mapper import to_message_data
from velkgram.ingestion.ports.telegram import (
    ChannelResolutionError,
    ResolvedChannel,
    TelegramDeferred,
)
from velkgram.shared.events import MessageData
from velkgram.shared.ports import Clock

_MAX_WAIT = 60


class TelethonGateway:
    def __init__(self, client: TelegramClient, clock: Clock) -> None:
        self._client = client
        self._clock = clock

    async def _entity(self, channel_id: int) -> Any:
        return await self._client.get_entity(channel_id)

    async def iter_since(
        self, channel_id: int, min_id: int | None, limit: int, not_before: datetime
    ) -> AsyncIterator[MessageData]:
        try:
            entity = await self._entity(channel_id)
            async for msg in self._client.iter_messages(
                entity, min_id=min_id or 0, offset_date=not_before, reverse=True, limit=limit
            ):
                if isinstance(msg, types.Message):
                    yield to_message_data(msg, channel_id, self._clock.now(), "backfill")
        except errors.FloodWaitError as exc:
            if exc.seconds > _MAX_WAIT:
                raise TelegramDeferred(exc.seconds) from exc
            raise

    async def latest_message_id(self, channel_id: int) -> int | None:
        try:
            entity = await self._entity(channel_id)
            async for msg in self._client.iter_messages(entity, limit=1):
                return int(msg.id)
        except errors.FloodWaitError as exc:
            if exc.seconds > _MAX_WAIT:
                raise TelegramDeferred(exc.seconds) from exc
            raise
        return None

    async def resolve_and_join(self, ref: str) -> ResolvedChannel:
        try:
            entity = await self._resolve(ref)
        except (
            errors.InviteHashInvalidError,
            errors.InviteHashExpiredError,
            errors.UsernameInvalidError,
            errors.UsernameNotOccupiedError,
        ) as exc:
            raise ChannelResolutionError("Link inválido ou expirado") from exc
        except errors.FloodWaitError as exc:
            if exc.seconds > _MAX_WAIT:
                raise ChannelResolutionError(
                    f"Telegram pediu espera de {exc.seconds} s, tente depois"
                ) from exc
            raise
        if not isinstance(entity, types.Channel) or not entity.broadcast:
            raise ChannelResolutionError("Não é um canal")
        return ResolvedChannel(telegram_id=utils.get_peer_id(entity), title=entity.title)

    async def _resolve(self, ref: str) -> Any:
        client: Any = self._client
        if ref.startswith("+"):
            invite_hash = ref[1:]
            check = await client(functions.messages.CheckChatInviteRequest(invite_hash))
            if isinstance(check, types.ChatInviteAlready):
                return check.chat
            try:
                updates = await client(functions.messages.ImportChatInviteRequest(invite_hash))
            except errors.UserAlreadyParticipantError:
                return await client.get_entity(ref)
            return updates.chats[0]
        entity = await client.get_entity(ref)
        await client(functions.channels.JoinChannelRequest(entity))  # idempotent
        return entity

    async def warm_entity_cache(self) -> None:
        await self._client.get_dialogs()

    def is_connected(self) -> bool:
        return bool(self._client.is_connected())
