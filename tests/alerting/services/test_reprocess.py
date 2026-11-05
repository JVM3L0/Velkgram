from dataclasses import replace
from datetime import timedelta

from tests.alerting.services.test_evaluate import Harness
from tests.fakes.messages import NOW, msg
from tests.fakes.repositories import InMemoryAlertRepository
from velkgram.alerting import Alert
from velkgram.alerting.adapters.wishlist_api import WishlistApiReader
from velkgram.alerting.domain.dedup import DedupCache
from velkgram.alerting.services.evaluate import Evaluator
from velkgram.alerting.services.reprocess import reprocess_unprocessed
from velkgram.alerting.services.retry_failed import warm_cache
from velkgram.shared.events import MessageReceived


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


def _restart(h: Harness) -> Evaluator:
    cache = DedupCache(timedelta(minutes=30))
    warm_cache(h.alerts, cache, h.clock)
    return Evaluator(
        wishes=WishlistApiReader(h.wishes),
        repo=h.alerts,
        cache=cache,
        notifier=h.notifier,
        bus=h.bus,
        clock=h.clock,
        mark_processed=lambda c, m: h.processed.append((c, m)),
        channel_names=lambda: {10: "Promos"},
        sleep=h._no_sleep,
    )


async def test_restart_with_warm_cache_does_not_duplicate() -> None:
    h = Harness()
    h.wish()
    m = msg(1, text="RTX 4060 por R$ 1.500,00")
    await h.feed(m)
    assert len(h.stored()) == 1
    restarted = _restart(h)
    await restarted.on_received(MessageReceived(m))
    await restarted.wait_idle()
    assert len(h.stored()) == 1
    assert len(h.notifier.sent) == 1


class _FailingForWish(InMemoryAlertRepository):
    fail_wish: int | None = None

    def add(self, a: Alert) -> Alert:
        if a.wish_id == self.fail_wish:
            raise RuntimeError("db down")
        return super().add(a)


async def test_partially_evaluated_message_alerts_only_missing_wish() -> None:
    h = Harness()
    repo = _FailingForWish()
    h.alerts = repo
    h.evaluator = Evaluator(
        wishes=WishlistApiReader(h.wishes),
        repo=repo,
        cache=DedupCache(timedelta(minutes=30)),
        notifier=h.notifier,
        bus=h.bus,
        clock=h.clock,
        mark_processed=lambda c, m: h.processed.append((c, m)),
        channel_names=lambda: {10: "Promos"},
        sleep=h._no_sleep,
    )
    h.wish("A", ("rtx 4060",))
    h.wish("B", ("rtx 4060",))
    repo.fail_wish = 2
    m = msg(1, text="RTX 4060 por R$ 1.500,00")
    await h.feed(m)
    assert [a.wish_id for a in h.stored()] == [1]
    assert h.processed == []
    repo.fail_wish = None
    restarted = _restart(h)
    await restarted.on_received(MessageReceived(m))
    await restarted.wait_idle()
    assert sorted(a.wish_id for a in h.stored()) == [1, 2]
    assert h.processed == [(10, 1)]
