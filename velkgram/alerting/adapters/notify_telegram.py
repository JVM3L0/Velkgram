"""Notifier that delivers alerts through a Telegram bot.

Telethon is never imported here: the client satisfies `BotClient` structurally and
errors are classified by class name.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from velkgram.alerting.domain.format import format_alert
from velkgram.alerting.domain.models import AlertMessage
from velkgram.alerting.ports.notifier import NotifierError
from velkgram.alerting.ports.notifier_state import NotifierStateStore, NotifierStatus
from velkgram.shared.ports import Clock

log = logging.getLogger(__name__)


class BotClient(Protocol):
    async def start(self, bot_token: str) -> None: ...

    async def send_message(self, chat_id: int, text: str, *, link_preview: bool) -> None: ...

    async def disconnect(self) -> None: ...


class TelegramBotNotifier:
    attempt_timeout = 10.0
    LOGIN_TIMEOUT_S = 8.0
    LOGIN_RETRY_S = 60.0
    SYSTEM_TIMEOUT_S = 10.0
    DISCONNECT_TIMEOUT_S = 2.0
    MIN_INTERVAL_S = 1.0
    NEEDS_START = frozenset({"UserIsBlockedError", "PeerIdInvalidError", "ValueError"})
    LOGIN_LOST = frozenset(
        {
            "AuthKeyUnregisteredError",
            "AccessTokenExpiredError",
            "AccessTokenInvalidError",
            "AuthKeyDuplicatedError",
            "SessionRevokedError",
        }
    )

    def __init__(
        self,
        client: BotClient,
        token: str,
        chat_id: Callable[[], int | None],
        state: NotifierStateStore,
        clock: Clock,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._token = token
        self._chat_id = chat_id
        self._state = state
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._started = False
        self._login_task: asyncio.Task[None] | None = None
        self._next_login_at: float | None = None
        self._last_send_at: float | None = None

    def _record(self, status: NotifierStatus, detail: str | None) -> None:
        self._state.set(status, detail, self._clock.now())

    def begin_login(self, force: bool = False) -> None:
        if self._started:
            return
        if self._login_task is not None and not self._login_task.done():
            return
        now = self._monotonic()
        if not force and self._next_login_at is not None and now < self._next_login_at:
            return
        self._next_login_at = now + self.LOGIN_RETRY_S
        self._login_task = asyncio.create_task(self._login())

    async def _login(self) -> None:
        try:
            async with asyncio.timeout(self.LOGIN_TIMEOUT_S):
                await self._client.start(self._token)
        except Exception as exc:
            name = type(exc).__name__
            self._record(NotifierStatus.ERROR, name)
            log.warning("bot_login_failed", extra={"error": name})
            seconds = getattr(exc, "seconds", None)
            if "FloodWait" in name and isinstance(seconds, int):
                resume = self._monotonic() + seconds
                self._next_login_at = max(self._next_login_at or resume, resume)
            await self._disconnect()
        else:
            self._started = True
            self._record(NotifierStatus.OK, None)

    async def _disconnect(self) -> None:
        with contextlib.suppress(Exception):
            async with asyncio.timeout(self.DISCONNECT_TIMEOUT_S):
                await self._client.disconnect()

    async def ensure_started(self, force: bool = False) -> bool:
        if self._started:
            return True
        self.begin_login(force)
        task = self._login_task
        if task is not None and not task.done():
            await asyncio.shield(task)
        return self._started

    async def notify(self, message: AlertMessage) -> None:
        if not await self.ensure_started():
            raise NotifierError("bot_unavailable")
        await self._send(format_alert(message))

    async def notify_system(self, text: str) -> None:
        try:
            async with asyncio.timeout(self.SYSTEM_TIMEOUT_S):
                if not await self.ensure_started(force=True):
                    raise NotifierError("bot_unavailable")
                await self._send(text)
        except TimeoutError:
            raise NotifierError("timeout") from None

    async def _send(self, text: str) -> None:
        chat_id = self._chat_id()
        if chat_id is None:
            self._record(NotifierStatus.ERROR, "sem chat")
            raise NotifierError("no_chat")
        async with self._lock:
            if self._last_send_at is not None:
                wait = self._last_send_at + self.MIN_INTERVAL_S - self._monotonic()
                if wait > 0:
                    await self._sleep(wait)
            self._last_send_at = self._monotonic()
            failure: str | None = None
            try:
                await self._client.send_message(chat_id, text, link_preview=True)
            except Exception as exc:
                failure = type(exc).__name__
            if failure is not None:
                if failure in self.NEEDS_START:
                    self._record(NotifierStatus.NEEDS_START, None)
                else:
                    self._record(NotifierStatus.ERROR, failure)
                if failure in self.LOGIN_LOST:
                    self._started = False
                    await self._disconnect()
                # Raised outside the except block: no __context__ keeps the raw exception.
                raise NotifierError(failure)
            self._record(NotifierStatus.OK, None)

    async def aclose(self) -> None:
        task = self._login_task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._disconnect()
