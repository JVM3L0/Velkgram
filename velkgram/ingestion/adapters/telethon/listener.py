"""Register Telethon event handlers that feed the Ingestor."""

import logging

from telethon import TelegramClient, events

from velkgram.ingestion.adapters.telethon.mapper import to_message_data
from velkgram.ingestion.services.ingest import Ingestor
from velkgram.shared.ports import Clock

log = logging.getLogger(__name__)


def register_handlers(client: TelegramClient, ingestor: Ingestor, clock: Clock) -> None:
    """No `chats=` filter: the Ingestor's enabled set decides which channels count."""

    async def on_new(event: events.NewMessage.Event) -> None:
        received_at = clock.now()
        try:
            if event.chat_id is None:
                return
            m = to_message_data(event.message, event.chat_id, received_at, "live")
            await ingestor.on_new(m)
        except Exception:
            log.exception("telegram_handler_failed", extra={"handler": "new"})

    async def on_edit(event: events.MessageEdited.Event) -> None:
        received_at = clock.now()
        try:
            if event.chat_id is None:
                return
            msg = event.message
            m = to_message_data(msg, event.chat_id, received_at, "live")
            await ingestor.on_edit(m, edited_at=msg.edit_date or clock.now())
        except Exception:
            log.exception("telegram_handler_failed", extra={"handler": "edit"})

    async def on_delete(event: events.MessageDeleted.Event) -> None:
        clock.now()
        try:
            if event.chat_id is None:
                return
            await ingestor.on_delete(event.chat_id, event.deleted_ids)
        except Exception:
            log.exception("telegram_handler_failed", extra={"handler": "delete"})

    client.add_event_handler(on_new, events.NewMessage())
    client.add_event_handler(on_edit, events.MessageEdited())
    client.add_event_handler(on_delete, events.MessageDeleted())
