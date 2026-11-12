"""The profile page's "send a test alert": one message through the bot, on demand."""

import asyncio
from collections.abc import Awaitable, Callable

from velkgram.alerting.adapters.notify_telegram import TelegramBotNotifier
from velkgram.alerting.ports.notifier import NotifierError
from velkgram.alerting.ports.notifier_state import NotifierStatus
from velkgram.apps import notifier_wiring
from velkgram.apps.notifier_wiring import MemoryNotifierStateStore
from velkgram.shared.adapters.clock_system import SystemClock
from velkgram.shared.config import Settings

TIMEOUT_S = 20.0
TestSender = Callable[[int], Awaitable[str | None]]


def make_test_sender(settings: Settings) -> TestSender:
    """Send to a chat and return None, or a short error code ('disabled', the error name...).

    The web process opens its own bot session (the bot token allows several); it never touches
    the user's collector session, and its status writes go to a throwaway store.
    """

    async def send(chat_id: int) -> str | None:
        token = settings.alert_bot_token
        if settings.notifier != "telegram" or token is None:
            return "disabled"
        clock = SystemClock()
        state = MemoryNotifierStateStore()
        state.set(NotifierStatus.ERROR, "iniciando", clock.now())
        bot = TelegramBotNotifier(
            notifier_wiring.make_bot_client(settings),
            token,
            chat_id=lambda: chat_id,
            state=state,
            clock=clock,
        )
        try:
            async with asyncio.timeout(TIMEOUT_S):
                await bot.notify_system("Velkgram: teste de alerta ✅")
        except NotifierError as exc:
            row = state.get()
            if row is not None and row[0] is NotifierStatus.NEEDS_START:
                return "needs_start"
            return str(exc) or type(exc).__name__
        except TimeoutError:
            return "timeout"
        finally:
            await bot.aclose()
        return None

    return send
