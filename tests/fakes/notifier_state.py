from datetime import datetime

from velkgram.alerting.ports.notifier_state import NotifierStatus


class InMemoryNotifierStateStore:
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
