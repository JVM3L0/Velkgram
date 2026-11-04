"""Real Telethon TL objects built offline (no network)."""

from datetime import UTC, datetime

from telethon.tl import types

DATE = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def make_message(
    *,
    id: int = 1,
    text: str = "",
    entities: list[types.TypeMessageEntity] | None = None,
    buttons: list[str] | None = None,
    fwd_channel_id: int | None = None,
    fwd_post: int | None = None,
    grouped_id: int | None = None,
    photo: bool = False,
    edit_date: datetime | None = None,
) -> types.Message:
    markup = None
    if buttons:
        row = types.KeyboardInlineButtonRow(
            buttons=[
                types.KeyboardInlineButton(text="b", type=types.InlineButtonTypeUrl(url=u))
                for u in buttons
            ]
        )
        markup = types.ReplyInlineMarkup(rows=[row])
    fwd = None
    if fwd_channel_id is not None:
        fwd = types.MessageFwdHeader(
            date=DATE, from_id=types.PeerChannel(fwd_channel_id), channel_post=fwd_post
        )
    media = None
    if photo:
        media = types.MessageMediaPhoto(
            photo=types.Photo(
                id=1,
                access_hash=1,
                file_reference=b"",
                date=DATE,
                sizes=[],
                dc_id=1,
            )
        )
    return types.Message(
        id=id,
        peer_id=types.PeerChannel(100),
        date=DATE,
        message=text,
        entities=entities,
        reply_markup=markup,
        fwd_from=fwd,
        grouped_id=grouped_id,
        media=media,
        edit_date=edit_date,
    )
