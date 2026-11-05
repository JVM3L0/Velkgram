from datetime import UTC, datetime

from velkgram.shared.events import MessageData

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def msg(message_id: int = 1, channel_id: int = 10, text: str = "oferta") -> MessageData:
    return MessageData(
        channel_id=channel_id,
        message_id=message_id,
        date=NOW,
        received_at=NOW,
        text=text,
        links=(),
        fwd_from_channel_id=None,
        fwd_from_message_id=None,
        grouped_id=None,
        has_photo=False,
        source="live",
    )
