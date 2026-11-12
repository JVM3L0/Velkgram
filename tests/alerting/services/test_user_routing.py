import asyncio
from dataclasses import replace

import pytest

from tests.fakes.notifier import FakeNotifier
from velkgram.alerting import AlertMessage, NotifierError, send_with_retry
from velkgram.alerting.ports.notifier import NotConfigured
from velkgram.alerting.services.routing import UserRoutedNotifier

MSG = AlertMessage("RTX", "oferta", 100, "Promos", None, None)


class Directory:
    def __init__(self, chats: dict[int, int | None]) -> None:
        self._chats = chats

    def chat_id(self, user_id: int) -> int | None:
        return self._chats.get(user_id)


async def test_the_alert_goes_to_the_chat_of_its_user() -> None:
    inner = FakeNotifier()
    routed = UserRoutedNotifier(inner, Directory({1: 111, 2: 222}))
    await routed.notify(replace(MSG, user_id=2))
    await routed.notify(replace(MSG, user_id=1))
    assert [m.chat_id for m in inner.sent] == [222, 111]


async def test_a_user_without_a_chat_is_not_configured_and_nothing_is_sent() -> None:
    inner = FakeNotifier()
    routed = UserRoutedNotifier(inner, Directory({1: 111, 2: None}))
    with pytest.raises(NotConfigured):
        await routed.notify(replace(MSG, user_id=2))
    with pytest.raises(NotConfigured):
        await routed.notify(replace(MSG, user_id=99))  # unknown user
    assert inner.sent == []


async def test_system_messages_pass_straight_through() -> None:
    inner = FakeNotifier()
    await UserRoutedNotifier(inner, Directory({})).notify_system("coletor parou")
    assert inner.system == ["coletor parou"]


def test_not_configured_is_a_notifier_error() -> None:
    assert issubclass(NotConfigured, NotifierError)


async def test_send_with_retry_does_not_retry_a_missing_chat() -> None:
    inner = FakeNotifier()
    routed = UserRoutedNotifier(inner, Directory({1: None}))
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        await asyncio.sleep(0)

    ok, attempts, error = await send_with_retry(routed, MSG, sleep=sleep)
    assert (ok, attempts, error) == (False, 1, "no_chat")
    assert slept == []
