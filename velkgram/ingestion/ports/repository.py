"""Raw message persistence port. Message writes never bump state versions."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from velkgram.ingestion.domain.models import Heartbeat
from velkgram.shared.events import MessageData


class MessageRepository(Protocol):
    def add(self, m: MessageData) -> bool:
        """Store `m`; return False when it already exists."""
        ...

    def add_version(self, m: MessageData, edited_at: datetime, sold_out_hint: bool) -> int:
        """Store an edit of `m` and return its version number (1 for the first edit)."""
        ...

    def mark_deleted(self, channel_id: int, message_ids: Sequence[int], at: datetime) -> None: ...

    def mark_processed(self, channel_id: int, message_id: int, at: datetime) -> None: ...

    def list_unprocessed_since(self, since: datetime) -> list[MessageData]: ...

    def get(self, channel_id: int, message_id: int) -> MessageData | None: ...

    def get_cursor(self, channel_id: int) -> int | None: ...

    def set_cursor(self, channel_id: int, last_message_id: int) -> None:
        """Advance the cursor; a lower value is ignored."""
        ...

    def write_heartbeat(self, h: Heartbeat) -> None: ...

    def read_heartbeat(self) -> Heartbeat | None: ...
