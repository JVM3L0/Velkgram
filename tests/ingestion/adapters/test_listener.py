from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from telethon import events

from tests.fakes.clock import FakeClock
from tests.fixtures.telegram.factories import make_message
from velkgram.ingestion.adapters.telethon.listener import register_handlers

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _setup() -> tuple[dict[type, Any], AsyncMock]:
    handlers: dict[type, Any] = {}
    client = MagicMock()

    def add(cb: Any, ev: Any) -> None:
        handlers[type(ev)] = cb

    client.add_event_handler.side_effect = add
    ingestor = AsyncMock()
    register_handlers(client, ingestor, FakeClock(NOW))
    return handlers, ingestor


async def test_new_message_calls_on_new() -> None:
    handlers, ing = _setup()
    msg = make_message(id=3, text="x")
    await handlers[events.NewMessage](SimpleNamespace(message=msg, chat_id=-100100))
    m = ing.on_new.call_args.args[0]
    assert (m.channel_id, m.message_id, m.received_at, m.source) == (-100100, 3, NOW, "live")


async def test_edit_uses_edit_date_or_clock() -> None:
    handlers, ing = _setup()
    ed = datetime(2026, 11, 4, 11, 0, tzinfo=UTC)
    await handlers[events.MessageEdited](
        SimpleNamespace(message=make_message(id=3, text="x", edit_date=ed), chat_id=-100100)
    )
    assert ing.on_edit.call_args.kwargs["edited_at"] == ed
    await handlers[events.MessageEdited](
        SimpleNamespace(message=make_message(id=3, text="x"), chat_id=-100100)
    )
    assert ing.on_edit.call_args.kwargs["edited_at"] == NOW


async def test_delete_skips_without_chat_and_forwards_otherwise() -> None:
    handlers, ing = _setup()
    await handlers[events.MessageDeleted](SimpleNamespace(chat_id=None, deleted_ids=[1]))
    ing.on_delete.assert_not_called()
    await handlers[events.MessageDeleted](SimpleNamespace(chat_id=-100100, deleted_ids=[1, 2]))
    ing.on_delete.assert_awaited_once_with(-100100, [1, 2])


async def test_handler_swallows_exceptions() -> None:
    handlers, ing = _setup()
    ing.on_new.side_effect = RuntimeError("boom")
    await handlers[events.NewMessage](
        SimpleNamespace(message=make_message(id=3, text="x"), chat_id=-100100)
    )
