from dataclasses import replace
from datetime import timedelta

from tests.alerting.services.test_evaluate import Harness
from tests.fakes.messages import NOW, msg
from velkgram.alerting.services.reprocess import reprocess_unprocessed


async def test_reprocess_is_idempotent() -> None:
    h = Harness()
    h.wish()
    fresh = replace(msg(1, text="RTX 4060 por R$ 1.500,00"), received_at=NOW - timedelta(minutes=5))
    stale = replace(
        msg(2, text="RTX 4060 por R$ 1.400,00"), received_at=NOW - timedelta(minutes=45)
    )
    h.messages.add(fresh)
    h.messages.add(stale)

    def unprocessed(since):
        return h.messages.list_unprocessed_since(since)

    assert await reprocess_unprocessed(unprocessed, h.evaluator, h.clock) == 1
    assert len(h.stored()) == 1
    assert len(h.notifier.sent) == 1
    again = await reprocess_unprocessed(lambda _: [fresh], h.evaluator, h.clock)
    assert again == 1
    assert len(h.stored()) == 1
    assert len(h.notifier.sent) == 1
