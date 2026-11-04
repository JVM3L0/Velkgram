from tests.fakes.messages import msg
from tests.fakes.repositories import InMemoryMessageRepository
from tests.fakes.telegram import FakeTelegramGateway
from velkgram.ingestion.ports.telegram import TelegramDeferred
from velkgram.ingestion.services.gap_check import gap_check


async def test_gap_check_reports_channels_behind() -> None:
    repo = InMemoryMessageRepository()
    repo.set_cursor(10, 5)
    repo.set_cursor(11, 9)
    repo.set_cursor(13, 1)
    gw = FakeTelegramGateway(
        {10: [msg(7, 10)], 11: [msg(9, 11)], 12: [msg(2, 12)], 13: [msg(3, 13)], 14: []}, {}
    )
    gw.deferred[13] = TelegramDeferred(90)
    # 12 has no cursor but has messages: behind. 13 is deferred: skipped. 14 is empty: fine.
    assert await gap_check(gw, repo, [10, 11, 12, 13, 14]) == [10, 12]
