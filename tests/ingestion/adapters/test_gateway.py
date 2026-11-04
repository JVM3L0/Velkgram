from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon import errors
from telethon.tl import functions, types

from tests.fakes.clock import FakeClock
from tests.fixtures.telegram.factories import make_message
from velkgram.ingestion.adapters.telethon.client import is_auth_fatal
from velkgram.ingestion.adapters.telethon.gateway import TelethonGateway
from velkgram.ingestion.ports.telegram import ChannelResolutionError, TelegramDeferred

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _flood(seconds: int) -> errors.FloodWaitError:
    e = errors.FloodWaitError(request=None)
    e.seconds = seconds
    return e


def _channel(broadcast: bool = True) -> types.Channel:
    return types.Channel(
        id=42,
        title="Promo",
        photo=types.ChatPhotoEmpty(),
        date=NOW,
        broadcast=broadcast,
        megagroup=not broadcast,
    )


def _gw(client: Any) -> TelethonGateway:
    return TelethonGateway(client, FakeClock(NOW))


async def test_iter_since_passes_reverse_min_id_offset_date() -> None:
    client = AsyncMock()
    entity = _channel()
    client.get_entity.return_value = entity

    async def gen(*_a: Any, **_k: Any) -> AsyncIterator[types.Message]:
        yield make_message(id=5, text="hi")

    client.iter_messages = MagicMock(side_effect=gen)
    out = [m async for m in _gw(client).iter_since(-1000000000042, 4, 50, NOW)]
    client.iter_messages.assert_called_once_with(
        entity, min_id=4, offset_date=NOW, reverse=True, limit=50
    )
    assert [(m.message_id, m.channel_id, m.source) for m in out] == [
        (5, -1000000000042, "backfill")
    ]


async def test_iter_since_flood_wait_over_60s_raises_deferred() -> None:
    client = AsyncMock()

    def boom(*_a: Any, **_k: Any) -> AsyncIterator[Any]:
        raise _flood(120)

    client.iter_messages = MagicMock(side_effect=boom)
    with pytest.raises(TelegramDeferred) as ei:
        [m async for m in _gw(client).iter_since(-1000000000042, None, 5, NOW)]
    assert ei.value.seconds == 120


async def test_resolve_rejects_megagroup() -> None:
    client = AsyncMock()
    client.get_entity.return_value = _channel(broadcast=False)
    with pytest.raises(ChannelResolutionError, match="Não é um canal"):
        await _gw(client).resolve_and_join("@grupo")


async def test_resolve_username_joins_and_returns_peer_id() -> None:
    client = AsyncMock()
    client.get_entity.return_value = _channel()
    res = await _gw(client).resolve_and_join("@promo")
    assert (res.telegram_id, res.title) == (-1000000000042, "Promo")
    req = client.call_args.args[0]
    assert isinstance(req, functions.channels.JoinChannelRequest)


async def test_resolve_invite_hash_uses_import() -> None:
    client = AsyncMock()
    chat = _channel()
    client.side_effect = [
        types.ChatInvite(
            title="x",
            photo=types.PhotoEmpty(id=0),
            participants_count=1,
            participants=[],
            color=0,
        ),
        types.Updates(updates=[], users=[], chats=[chat], date=NOW, seq=0),
    ]
    res = await _gw(client).resolve_and_join("+abc")
    first, second = (c.args[0] for c in client.call_args_list)
    assert isinstance(first, functions.messages.CheckChatInviteRequest)
    assert isinstance(second, functions.messages.ImportChatInviteRequest)
    assert second.hash == "abc"
    assert res.telegram_id == -1000000000042


async def test_resolve_already_member_invite_returns_chat() -> None:
    client = AsyncMock()
    client.side_effect = [types.ChatInviteAlready(chat=_channel())]
    res = await _gw(client).resolve_and_join("+abc")
    assert res.title == "Promo"
    assert client.call_count == 1


async def test_resolve_invalid_invite_is_resolution_error() -> None:
    client = AsyncMock()
    client.side_effect = errors.InviteHashExpiredError(request=None)
    with pytest.raises(ChannelResolutionError, match="Link inválido ou expirado"):
        await _gw(client).resolve_and_join("+abc")


async def test_resolve_flood_wait_over_60s_raises_resolution_error() -> None:
    client = AsyncMock()
    client.get_entity.side_effect = _flood(300)
    with pytest.raises(ChannelResolutionError, match="espera de 300 s, tente depois"):
        await _gw(client).resolve_and_join("@promo")


async def test_latest_message_id_and_connected_and_warm() -> None:
    client = AsyncMock()
    client.get_entity.return_value = _channel()

    async def gen(*_a: Any, **_k: Any) -> AsyncIterator[types.Message]:
        yield make_message(id=9)

    client.iter_messages = MagicMock(side_effect=gen)
    client.is_connected = MagicMock(return_value=True)
    gw = _gw(client)
    assert await gw.latest_message_id(-1000000000042) == 9
    assert gw.is_connected() is True
    await gw.warm_entity_cache()
    client.get_dialogs.assert_awaited_once()


def test_is_auth_fatal() -> None:
    assert is_auth_fatal(errors.AuthKeyDuplicatedError(request=None))
    assert is_auth_fatal(errors.AuthKeyUnregisteredError(request=None))
    assert is_auth_fatal(errors.UserDeactivatedBanError(request=None))
    assert is_auth_fatal(errors.SessionRevokedError(request=None))
    assert not is_auth_fatal(ValueError("x"))
