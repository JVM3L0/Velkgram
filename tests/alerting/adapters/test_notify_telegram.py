import asyncio
import logging
from datetime import UTC, datetime

import pytest

from tests.fakes.bot_client import FakeBotClient, FakeMonotonic
from tests.fakes.clock import FakeClock
from tests.fakes.notifier_state import InMemoryNotifierStateStore
from velkgram.alerting import AlertMessage, NotifierError, format_alert
from velkgram.alerting.adapters.notify_telegram import TelegramBotNotifier
from velkgram.alerting.ports.notifier_state import NotifierStatus

TOKEN = "123:SECRET-TOKEN"
MSG = AlertMessage("RTX 4060", "oferta", 150000, "Promos", None, None)


class UserIsBlockedError(Exception): ...


class PeerIdInvalidError(Exception): ...


class AuthKeyUnregisteredError(Exception): ...


class FloodWaitError(Exception):
    def __init__(self, seconds: int) -> None:
        super().__init__("flood")
        self.seconds = seconds


class Boom(Exception): ...


class Env:
    def __init__(self, chat: int | None = 42) -> None:
        self.mono = FakeMonotonic()
        self.client = FakeBotClient(self.mono)
        self.state = InMemoryNotifierStateStore()
        self.chat = chat
        self.notifier = TelegramBotNotifier(
            self.client,
            TOKEN,
            lambda: self.chat,
            self.state,
            FakeClock(datetime(2026, 11, 6, tzinfo=UTC)),
            monotonic=self.mono,
            sleep=self.mono.sleep,
        )

    def status(self) -> tuple[NotifierStatus, str | None] | None:
        row = self.state.get()
        return None if row is None else (row[0], row[1])


@pytest.fixture
def env() -> Env:
    return Env()


async def test_notify_sends_text_with_preview(env: Env) -> None:
    await env.notifier.notify(MSG)
    assert env.client.sent == [(42, format_alert(MSG), True)]
    assert env.client.start_calls == [TOKEN]
    assert env.status() == (NotifierStatus.OK, None)


async def test_notify_system_sends_text_with_preview(env: Env) -> None:
    await env.notifier.notify_system("Velkgram parou")
    assert env.client.sent == [(42, "Velkgram parou", True)]


async def test_concurrent_sends_are_paced(env: Env) -> None:
    await asyncio.gather(*(env.notifier.notify(MSG) for _ in range(3)))
    assert env.client.send_times == [0.0, 1.0, 2.0]
    assert env.mono.sleeps == [1.0, 1.0]


async def test_burst_of_ten_delivers_all_in_order(env: Env) -> None:
    messages = [AlertMessage(f"w{i}", f"t{i}", None, "c", None, None) for i in range(10)]
    await asyncio.gather(*(env.notifier.notify(m) for m in messages))
    assert [s[1] for s in env.client.sent] == [format_alert(m) for m in messages]


async def test_send_error_becomes_notifier_error_with_class_name(env: Env) -> None:
    env.client.send_error = Boom("detail")
    with pytest.raises(NotifierError, match="Boom") as info:
        await env.notifier.notify(MSG)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__
    assert env.status() == (NotifierStatus.ERROR, "Boom")


@pytest.mark.parametrize("exc", [ValueError("x"), PeerIdInvalidError(), UserIsBlockedError()])
async def test_unreachable_user_records_needs_start(env: Env, exc: Exception) -> None:
    env.client.send_error = exc
    with pytest.raises(NotifierError):
        await env.notifier.notify(MSG)
    assert env.status() == (NotifierStatus.NEEDS_START, None)


async def test_failed_login_is_throttled_for_60s(env: Env) -> None:
    env.client.start_error = Boom()
    with pytest.raises(NotifierError, match="bot_unavailable"):
        await env.notifier.notify(MSG)
    env.mono.value = 30.0
    with pytest.raises(NotifierError, match="bot_unavailable"):
        await env.notifier.notify(MSG)
    assert len(env.client.start_calls) == 1
    env.mono.value = 60.0
    env.client.start_error = None
    await env.notifier.notify(MSG)
    assert len(env.client.start_calls) == 2
    assert len(env.client.sent) == 1


async def test_system_alert_bypasses_login_throttle(env: Env) -> None:
    env.client.start_error = Boom()
    with pytest.raises(NotifierError):
        await env.notifier.notify(MSG)
    env.mono.value = 5.0
    env.client.start_error = None
    await env.notifier.notify_system("parou")
    assert len(env.client.start_calls) == 2


async def test_flood_wait_pushes_next_login(env: Env) -> None:
    env.client.start_error = FloodWaitError(300)
    with pytest.raises(NotifierError):
        await env.notifier.notify(MSG)
    env.mono.value = 100.0
    with pytest.raises(NotifierError):
        await env.notifier.notify(MSG)
    assert len(env.client.start_calls) == 1


async def test_concurrent_sends_share_one_login(env: Env) -> None:
    env.client.start_gate = asyncio.Event()
    tasks = [asyncio.create_task(env.notifier.notify(MSG)) for _ in range(5)]
    await asyncio.sleep(0.01)
    env.client.start_gate.set()
    await asyncio.gather(*tasks)
    assert len(env.client.start_calls) == 1
    assert len(env.client.sent) == 5


async def test_cancelled_waiter_does_not_cancel_login(env: Env) -> None:
    env.client.start_gate = asyncio.Event()
    first = asyncio.create_task(env.notifier.notify(MSG))
    second = asyncio.create_task(env.notifier.notify(MSG))
    await asyncio.sleep(0.01)
    first.cancel()
    await asyncio.sleep(0.01)
    env.client.start_gate.set()
    await second
    assert len(env.client.start_calls) == 1
    assert len(env.client.sent) == 1


async def test_login_timeout_records_error_and_disconnects(env: Env) -> None:
    env.client.start_gate = asyncio.Event()
    env.notifier.LOGIN_TIMEOUT_S = 0.05
    with pytest.raises(NotifierError, match="bot_unavailable"):
        await env.notifier.notify(MSG)
    assert env.status() == (NotifierStatus.ERROR, "TimeoutError")
    assert env.client.disconnects == 1


async def test_hung_disconnect_does_not_block_next_login(env: Env) -> None:
    env.client.start_error = Boom()
    env.client.disconnect_gate = asyncio.Event()
    env.notifier.DISCONNECT_TIMEOUT_S = 0.05
    with pytest.raises(NotifierError):
        await env.notifier.notify(MSG)
    env.mono.value = 60.0
    env.client.start_error = None
    await env.notifier.notify(MSG)
    assert len(env.client.start_calls) == 2


async def test_lost_authorization_triggers_new_login(env: Env) -> None:
    await env.notifier.notify(MSG)
    env.client.send_error = AuthKeyUnregisteredError()
    with pytest.raises(NotifierError, match="AuthKeyUnregisteredError"):
        await env.notifier.notify(MSG)
    env.client.send_error = None
    env.mono.value = 60.0
    await env.notifier.notify(MSG)
    assert len(env.client.start_calls) == 2


async def test_system_alert_with_hung_send_times_out(env: Env) -> None:
    env.client.send_gate = asyncio.Event()
    env.notifier.SYSTEM_TIMEOUT_S = 0.05
    with pytest.raises(NotifierError, match="timeout") as info:
        await env.notifier.notify_system("parou")
    assert info.value.__cause__ is None


async def test_no_chat_records_error() -> None:
    env = Env(chat=None)
    with pytest.raises(NotifierError, match="no_chat"):
        await env.notifier.notify(MSG)
    assert env.status() == (NotifierStatus.ERROR, "sem chat")


async def test_token_never_leaks(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    env.client.start_error = RuntimeError(f"bad {TOKEN}")
    with pytest.raises(NotifierError) as info:
        await env.notifier.notify(MSG)
    with pytest.raises(NotifierError):
        await env.notifier.notify_system("parou")
    assert TOKEN not in caplog.text
    for record in caplog.records:
        assert all(TOKEN not in str(v) for v in record.__dict__.values())
    exc: BaseException | None = info.value
    while exc is not None:
        assert TOKEN not in str(exc)
        exc = exc.__cause__ or exc.__context__
    row = env.state.get()
    assert row is not None
    assert TOKEN not in str(row[1])


async def test_aclose_cancels_pending_login_and_disconnects(env: Env) -> None:
    env.client.start_gate = asyncio.Event()
    env.notifier.begin_login()
    await asyncio.sleep(0.01)
    await env.notifier.aclose()
    assert env.client.disconnects == 1
    assert env.notifier._login_task is not None  # pyright: ignore[reportPrivateUsage]
    assert env.notifier._login_task.cancelled()  # pyright: ignore[reportPrivateUsage]
