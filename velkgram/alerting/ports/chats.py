"""Where an alert goes: the chat of the user who owns the wish."""

from typing import Protocol


class ChatDirectory(Protocol):
    def chat_id(self, user_id: int) -> int | None:
        """The Telegram chat of an enabled user, or None when there is nothing to send to."""
        ...
