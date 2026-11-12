"""The "send a test alert" actions: a message through the bot, on demand."""

import asyncio
from collections.abc import Sequence
from typing import Protocol

from velkgram.alerting.adapters.notify_telegram import TelegramBotNotifier
from velkgram.alerting.ports.notifier import NotifierError
from velkgram.alerting.ports.notifier_state import NotifierStatus
from velkgram.apps import notifier_wiring
from velkgram.apps.notifier_wiring import MemoryNotifierStateStore
from velkgram.shared.adapters.clock_system import SystemClock
from velkgram.shared.config import Settings

PER_CHAT_TIMEOUT_S = 15.0
_TEXT = "Velkgram: teste de alerta ✅"


class Tester(Protocol):
    async def send_one(self, chat_id: int) -> str | None: ...

    async def send_many(self, chat_ids: Sequence[int]) -> dict[int, str | None]: ...


class TelegramTester:
    """Answers per chat with None (sent) or a short error code ('disabled', 'needs_start'...).

    The web process opens its own bot session (the bot token allows several) and sends every
    message through that one session: logging the bot in again for each user would risk a flood
    wait. It never touches the user's collector session, and its status writes go to a
    throwaway store.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send_one(self, chat_id: int) -> str | None:
        return (await self.send_many([chat_id]))[chat_id]

    async def send_many(self, chat_ids: Sequence[int]) -> dict[int, str | None]:
        chats = list(dict.fromkeys(chat_ids))  # a chat shared by two users gets one message
        if not chats:
            return {}
        token = self._settings.alert_bot_token
        if self._settings.notifier != "telegram" or token is None:
            return dict.fromkeys(chats, "disabled")
        clock = SystemClock()
        state = MemoryNotifierStateStore()
        current = [chats[0]]
        bot = TelegramBotNotifier(
            notifier_wiring.make_bot_client(self._settings),
            token,
            chat_id=lambda: current[0],
            state=state,
            clock=clock,
        )
        results: dict[int, str | None] = {}
        try:
            for chat in chats:
                current[0] = chat
                state.set(NotifierStatus.ERROR, "iniciando", clock.now())
                results[chat] = await self._send(bot, state)
        finally:
            await bot.aclose()
        return results

    @staticmethod
    async def _send(bot: TelegramBotNotifier, state: MemoryNotifierStateStore) -> str | None:
        try:
            async with asyncio.timeout(PER_CHAT_TIMEOUT_S):
                await bot.notify_system(_TEXT)
        except NotifierError as exc:
            row = state.get()
            if row is not None and row[0] is NotifierStatus.NEEDS_START:
                return "needs_start"
            return str(exc) or type(exc).__name__
        except TimeoutError:
            return "timeout"
        return None
