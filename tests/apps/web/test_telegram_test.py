import pytest

from tests.fakes.bot_client import FakeBotClient
from velkgram.apps import notifier_wiring
from velkgram.apps.web.telegram_test import TelegramTester
from velkgram.shared.config import Settings

TELEGRAM = Settings(notifier="telegram", alert_bot_token="123:TOKEN")


class UserIsBlockedError(Exception): ...


class Boom(Exception): ...


@pytest.fixture
def bot(monkeypatch: pytest.MonkeyPatch) -> FakeBotClient:
    client = FakeBotClient()
    monkeypatch.setattr(notifier_wiring, "make_bot_client", lambda _settings: client)
    return client


async def test_the_test_alert_goes_to_the_given_chat(bot: FakeBotClient) -> None:
    assert await TelegramTester(TELEGRAM).send_one(4242) is None
    assert [chat for chat, _, _ in bot.sent] == [4242]
    assert bot.disconnects == 1  # the web process never keeps a bot session open


@pytest.mark.parametrize(
    "settings", [Settings(notifier="log"), Settings(notifier="telegram", alert_bot_token=None)]
)
async def test_it_is_disabled_without_the_telegram_notifier(settings: Settings) -> None:
    assert await TelegramTester(settings).send_one(1) == "disabled"


async def test_a_user_who_never_pressed_start_gets_the_needs_start_code(bot: FakeBotClient) -> None:
    bot.send_error = UserIsBlockedError()
    assert await TelegramTester(TELEGRAM).send_one(4242) == "needs_start"
    assert bot.disconnects == 1


async def test_another_failure_returns_its_error_text(bot: FakeBotClient) -> None:
    bot.send_error = Boom()
    result = await TelegramTester(TELEGRAM).send_one(4242)
    assert result is not None and result != "needs_start"


async def test_many_chats_share_one_bot_session_and_each_gets_its_own_result(
    bot: FakeBotClient,
) -> None:
    results = await TelegramTester(TELEGRAM).send_many([111, 222, 333])
    assert results == {111: None, 222: None, 333: None}
    assert [chat for chat, _, _ in bot.sent] == [111, 222, 333]
    assert len(bot.start_calls) == 1  # one login for all of them, never one per user
    assert bot.disconnects == 1


async def test_one_failing_chat_does_not_stop_the_others(bot: FakeBotClient) -> None:
    class Flaky(FakeBotClient): ...

    calls = {"n": 0}
    original = bot.send_message

    async def send(chat_id: int, text: str, *, link_preview: bool) -> None:
        calls["n"] += 1
        if chat_id == 222:
            raise UserIsBlockedError()
        await original(chat_id, text, link_preview=link_preview)

    bot.send_message = send  # type: ignore[method-assign]
    results = await TelegramTester(TELEGRAM).send_many([111, 222, 333])
    assert results == {111: None, 222: "needs_start", 333: None}
    assert calls["n"] == 3


async def test_many_with_no_chats_does_nothing(bot: FakeBotClient) -> None:
    assert await TelegramTester(TELEGRAM).send_many([]) == {}
    assert bot.start_calls == []
