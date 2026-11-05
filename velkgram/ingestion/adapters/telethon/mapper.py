"""Telethon Message -> MessageData."""

from datetime import datetime
from typing import Literal, cast

from telethon import utils
from telethon.tl import types
from telethon.tl.custom import Message

from velkgram.shared.events import MessageData


def _links(msg: Message) -> tuple[str, ...]:
    found: list[str] = []
    for ent in msg.entities or []:
        if isinstance(ent, types.MessageEntityTextUrl):
            found.append(ent.url)
    # get_entities_text slices by UTF-16 offsets, so emoji before a URL are safe
    for _ent, url in msg.get_entities_text(types.MessageEntityUrl):
        found.append(url)
    markup = msg.reply_markup
    if isinstance(markup, types.ReplyInlineMarkup):
        for row in markup.rows:
            for button in row.buttons:
                if isinstance(button.type, types.InlineButtonTypeUrl):
                    found.append(button.type.url)
    return tuple(dict.fromkeys(found))


def to_message_data(
    raw: types.Message | Message,
    channel_id: int,
    received_at: datetime,
    source: Literal["live", "backfill"],
) -> MessageData:
    # Telethon patches types.Message with custom.Message at runtime; stubs do not know that.
    msg = cast(Message, raw)
    fwd_channel: int | None = None
    fwd_post: int | None = None
    fwd = msg.fwd_from
    if fwd is not None:
        if isinstance(fwd.from_id, types.PeerChannel):
            fwd_channel = utils.get_peer_id(types.PeerChannel(fwd.from_id.channel_id))
        fwd_post = fwd.channel_post
    return MessageData(
        channel_id=channel_id,
        message_id=msg.id,
        date=msg.date or received_at,
        received_at=received_at,
        text=msg.message or "",
        links=_links(msg),
        fwd_from_channel_id=fwd_channel,
        fwd_from_message_id=fwd_post,
        grouped_id=msg.grouped_id,
        has_photo=msg.photo is not None,
        source=source,
    )
