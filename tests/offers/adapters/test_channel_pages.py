from datetime import UTC, datetime

import httpx
import pytest

from tests.fakes.repositories import InMemoryChannelRepository
from velkgram.channels import Channel, ChannelStatus
from velkgram.offers.adapters.channels_api import ChannelsApiPublicChannels
from velkgram.offers.adapters.http.channel_pages import HttpxChannelPages


def _pages(handler: httpx.MockTransport) -> HttpxChannelPages:
    return HttpxChannelPages(client=httpx.Client(transport=handler))


def test_fetch_returns_the_html_of_the_public_web_view() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="<html>ok</html>")

    assert _pages(httpx.MockTransport(handler)).fetch("fumotom") == "<html>ok</html>"
    assert str(seen[0].url) == "https://t.me/s/fumotom"
    assert seen[0].headers["user-agent"].startswith("Velkgram/")


def test_fetch_an_older_page_passes_the_before_id() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="ok")

    assert _pages(httpx.MockTransport(handler)).fetch("fumotom", before=48835) == "ok"
    assert str(seen[0].url) == "https://t.me/s/fumotom?before=48835"


@pytest.mark.parametrize("status", [301, 403, 404, 429, 500])
def test_fetch_is_none_on_a_non_200_answer(status: int) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(status, text="x"))
    assert _pages(transport).fetch("fumotom") is None


def test_fetch_is_none_on_a_network_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    assert _pages(httpx.MockTransport(boom)).fetch("fumotom") is None


@pytest.mark.parametrize("name", ["", "ab", "a/b", "x y", "../etc", "a" * 40, "cafébom"])
def test_fetch_never_requests_an_invalid_username(name: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not request")

    assert _pages(httpx.MockTransport(handler)).fetch(name) is None


def _channel(ref: str, telegram_id: int | None, *, enabled: bool = True) -> Channel:
    return Channel(
        None, ref, telegram_id, ref, ChannelStatus.ACTIVE, None, enabled, 12,
        datetime(2026, 3, 1, tzinfo=UTC),
    )  # fmt: skip


def test_public_channels_lists_enabled_active_channels_with_a_username() -> None:
    repo = InMemoryChannelRepository()
    repo.add(_channel("@promotom", -100))
    repo.add(_channel("+inviteHash", -200))  # private invite: no public web view
    repo.add(_channel("@nopeid", None))  # not resolved yet
    repo.add(_channel("@off", -300, enabled=False))
    assert ChannelsApiPublicChannels(repo).public_channels() == [(-100, "promotom")]
