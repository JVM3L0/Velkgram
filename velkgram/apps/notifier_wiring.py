"""Wiring shared by the collector and the CLI for the Telegram bot notifier."""

from dataclasses import dataclass
from datetime import datetime

from velkgram.alerting.adapters.notify_telegram import BotClient
from velkgram.alerting.ports.notifier_state import NotifierStateStore, NotifierStatus
from velkgram.ingestion.adapters.telethon.client import build_bot_client
from velkgram.shared.config import Settings


@dataclass
class ChatHolder:
    """Where alerts go: ALERT_CHAT_ID, else this run's get_me(), else the stored chat id."""

    override: int | None
    current: int | None = None

    def resolve(self, state: NotifierStateStore) -> int | None:
        if self.override is not None:
            return self.override
        if self.current is not None:
            return self.current
        return state.get_chat_id()


def make_bot_client(settings: Settings) -> BotClient:
    return build_bot_client(settings)


class MemoryNotifierStateStore:
    """Throwaway state store: lets a diagnostic run without touching the shared row."""

    def __init__(self) -> None:
        self._row: tuple[NotifierStatus, str | None, datetime] | None = None
        self._chat_id: int | None = None

    def set(self, status: NotifierStatus, detail: str | None, at: datetime) -> None:
        if self._row is not None and self._row[:2] == (status, detail):
            return
        self._row = (status, detail, at)

    def get(self) -> tuple[NotifierStatus, str | None, datetime] | None:
        return self._row

    def set_chat_id(self, chat_id: int) -> None:
        if self._row is not None:
            self._chat_id = chat_id

    def get_chat_id(self) -> int | None:
        return self._chat_id if self._row is not None else None
