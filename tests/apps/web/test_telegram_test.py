import pytest

from tests.fakes.bot_client import FakeBotClient
from velkgram.apps import notifier_wiring
from velkgram.apps.web.telegram_test import make_test_sender
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
    assert await make_test_sender(TELEGRAM)(4242) is None
    assert [chat for chat, _, _ in bot.sent] == [4242]
    assert bot.disconnects == 1  # the web process never keeps a bot session open


@pytest.mark.parametrize(
    "settings", [Settings(notifier="log"), Settings(notifier="telegram", alert_bot_token=None)]
)
async def test_it_is_disabled_without_the_telegram_notifier(settings: Settings) -> None:
    assert await make_test_sender(settings)(1) == "disabled"


async def test_a_user_who_never_pressed_start_gets_the_needs_start_code(bot: FakeBotClient) -> None:
    bot.send_error = UserIsBlockedError()
    assert await make_test_sender(TELEGRAM)(4242) == "needs_start"
    assert bot.disconnects == 1


async def test_another_failure_returns_its_error_text(bot: FakeBotClient) -> None:
    bot.send_error = Boom()
    result = await make_test_sender(TELEGRAM)(4242)
    assert result is not None and result != "needs_start"
