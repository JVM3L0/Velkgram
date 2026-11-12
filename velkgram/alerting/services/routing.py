"""Route each alert to the chat of its user, in front of the real notifier."""

from dataclasses import replace

from velkgram.alerting.domain.models import AlertMessage
from velkgram.alerting.ports.chats import ChatDirectory
from velkgram.alerting.ports.notifier import NotConfigured, Notifier


class UserRoutedNotifier:
    """Alerts need a chat for their user; system messages go to the notifier's own chat."""

    def __init__(self, inner: Notifier, chats: ChatDirectory) -> None:
        self._inner = inner
        self._chats = chats

    async def notify(self, message: AlertMessage) -> None:
        chat_id = self._chats.chat_id(message.user_id)
        if chat_id is None:
            raise NotConfigured("no_chat")  # never fall back to someone else's chat
        await self._inner.notify(replace(message, chat_id=chat_id))

    async def notify_system(self, text: str) -> None:
        await self._inner.notify_system(text)
