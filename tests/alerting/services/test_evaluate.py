import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.messages import NOW, msg
from tests.fakes.notifier import FakeNotifier
from tests.fakes.repositories import (
    InMemoryAlertRepository,
    InMemoryMessageRepository,
    InMemoryWishRepository,
)
from velkgram.alerting import Alert, AlertStatus
from velkgram.alerting.adapters.wishlist_api import WishlistApiReader
from velkgram.alerting.domain.dedup import DedupCache
from velkgram.alerting.domain.format import format_alert
from velkgram.alerting.services.evaluate import Evaluator
from velkgram.shared.adapters.bus_memory import MemoryBus
from velkgram.shared.events import AlertTriggered, MessageData, MessageReceived
from velkgram.wishlist import Wish


class Harness:
    def __init__(self, notifier: FakeNotifier | None = None) -> None:
        self.wishes = InMemoryWishRepository()
        self.alerts = InMemoryAlertRepository()
        self.messages = InMemoryMessageRepository()
        self.notifier = notifier or FakeNotifier()
        self.clock = FakeClock(NOW)
        self.bus = MemoryBus()
        self.processed: list[tuple[int, int]] = []
        self.sent_calls = 0
        self.triggered: list[AlertTriggered] = []
        self.bus.subscribe(AlertTriggered, self._collect)
        self.evaluator = Evaluator(
            wishes=WishlistApiReader(self.wishes),
            repo=self.alerts,
            cache=DedupCache(timedelta(minutes=30)),
            notifier=self.notifier,
            bus=self.bus,
            clock=self.clock,
            mark_processed=lambda c, m: self.processed.append((c, m)),
            channel_names=lambda: {10: "Promos"},
            on_alert_sent=self._sent,
            sleep=self._no_sleep,
        )

    async def _collect(self, e: AlertTriggered) -> None:
        self.triggered.append(e)

    def _sent(self) -> None:
        self.sent_calls += 1

    @staticmethod
    async def _no_sleep(_: float) -> None:
        return None

    def wish(
        self,
        name: str = "RTX 4060",
        terms: tuple[str, ...] = ("rtx 4060",),
        max_cents: int = 200000,
    ) -> None:
        self.wishes.add(Wish(None, name, terms, (), max_cents, True))

    async def feed(self, m: MessageData) -> None:
        await self.evaluator.on_received(MessageReceived(m))
        await self.evaluator.wait_idle()
        await self.bus.drain()

    def stored(self) -> list[Alert]:
        return self.alerts.list_since(NOW - timedelta(days=1))


async def test_match_with_price_under_max_alerts() -> None:
    h = Harness()
    h.wish()
    await h.feed(msg(text="RTX 4060 por R$ 1.500,00"))
    [a] = h.stored()
    assert a.status is AlertStatus.sent
    assert a.price_cents == 150000
    assert not a.price_unknown
    assert a.attempts == 1
    assert a.sent_at == NOW
    assert h.notifier.sent[0].wish_name == "RTX 4060"
    assert h.notifier.sent[0].channel_name == "Promos"
    assert h.notifier.sent[0].link is not None
    assert h.sent_calls == 1
    assert [(e.alert_id, e.status) for e in h.triggered] == [(a.id, "sent")]
    assert h.processed == [(10, 1)]


async def test_price_over_max_does_not_alert() -> None:
    h = Harness()
    h.wish(max_cents=100000)
    await h.feed(msg(text="RTX 4060 por R$ 1.500,00"))
    assert h.stored() == []
    assert h.processed == [(10, 1)]


async def test_caption_without_price_alerts_price_unknown() -> None:
    h = Harness()
    h.wish()
    await h.feed(msg(text="Corre! RTX 4060 com desconto"))
    [a] = h.stored()
    assert a.price_unknown
    assert a.price_cents is None


async def test_empty_text_never_alerts() -> None:
    h = Harness()
    h.wish()
    await h.feed(msg(text="   "))
    assert h.stored() == []


async def test_album_items_without_caption_do_not_alert() -> None:
    h = Harness()
    h.wish()
    m = replace(msg(text=""), grouped_id=99, has_photo=True)
    await h.feed(m)
    assert h.stored() == []
    assert h.notifier.calls == 0


async def test_forward_of_alerted_message_is_suppressed_origin() -> None:
    h = Harness()
    h.wish()
    await h.feed(msg(1, 10, "RTX 4060 por R$ 1.500"))
    fwd = replace(
        msg(7, 20, "RTX 4060 por R$ 1.400"), fwd_from_channel_id=10, fwd_from_message_id=1
    )
    await h.feed(fwd)
    assert len(h.stored()) == 1
    assert h.alerts.suppressions[0][:3] == (20, 7, 1)
    assert h.alerts.suppressions[0][3] == "origin"


async def test_same_wish_same_price_within_30min_suppressed() -> None:
    h = Harness()
    h.wish()
    await h.feed(msg(1, text="RTX 4060 por R$ 1.500"))
    h.clock.advance(29 * 60)
    await h.feed(msg(2, text="outra loja RTX 4060 por R$ 1.500"))
    assert len(h.stored()) == 1
    assert h.alerts.suppressions[0][3] == "wish_price"


async def test_same_wish_same_price_after_31min_alerts_again() -> None:
    h = Harness()
    h.wish()
    await h.feed(msg(1, text="RTX 4060 por R$ 1.500"))
    h.clock.advance(31 * 60)
    await h.feed(msg(2, text="outra loja RTX 4060 por R$ 1.500"))
    assert len(h.stored()) == 2


async def test_price_drop_alerts_again() -> None:
    h = Harness()
    h.wish()
    await h.feed(msg(1, text="RTX 4060 por R$ 1.500"))
    await h.feed(msg(2, text="RTX 4060 por R$ 1.400"))
    assert len(h.stored()) == 2


async def test_reposted_with_other_price_spelling_is_suppressed() -> None:
    h = Harness()
    h.wish()
    await h.feed(msg(1, text="RTX 4060 R$ 1.500,00"))
    await h.feed(msg(2, text="RTX 4060 por R$1500"))
    assert len(h.stored()) == 1


async def test_same_text_without_price_suppressed_by_text_hash() -> None:
    h = Harness()
    h.wish()
    await h.feed(msg(1, text="RTX 4060 liberada"))
    await h.feed(msg(2, text="RTX 4060   LIBERADA"))
    assert len(h.stored()) == 1
    assert h.alerts.suppressions[0][3] == "wish_text"


async def test_one_message_two_wishes_two_alerts() -> None:
    h = Harness()
    h.wish("RTX 4060", ("rtx 4060",))
    h.wish("Kit", ("ryzen",))
    await h.feed(msg(text="Kit Ryzen + RTX 4060 por R$ 1.500"))
    assert sorted(a.wish_id for a in h.stored()) == [1, 2]
    assert h.notifier.calls == 2


async def test_backfill_older_than_30min_not_alerted_but_processed() -> None:
    h = Harness()
    h.wish()
    h.clock.advance(31 * 60)
    await h.feed(replace(msg(text="RTX 4060 por R$ 1.500"), source="backfill"))
    assert h.stored() == []
    assert h.processed == [(10, 1)]


async def test_backfill_recent_sets_delayed_minutes() -> None:
    h = Harness()
    h.wish()
    h.clock.advance(12 * 60 + 30)
    await h.feed(replace(msg(text="RTX 4060 por R$ 1.500"), source="backfill"))
    [a] = h.stored()
    assert a.delayed_minutes == 12
    assert h.notifier.sent[0].delayed_minutes == 12


async def test_live_message_has_no_delayed_minutes() -> None:
    h = Harness()
    h.wish()
    await h.feed(msg(text="RTX 4060 por R$ 1.500"))
    assert h.stored()[0].delayed_minutes is None


async def test_notifier_failure_marks_failed() -> None:
    h = Harness(FakeNotifier(fail_times=99))
    h.wish()
    await h.feed(msg(text="RTX 4060 por R$ 1.500"))
    [a] = h.stored()
    assert a.status is AlertStatus.failed
    assert a.attempts == 3
    assert a.last_error == "boom 3"
    assert h.sent_calls == 0
    assert [e.status for e in h.triggered] == ["failed"]


async def test_latencies_are_recorded() -> None:
    h = Harness()
    h.wish()
    m = replace(msg(text="RTX 4060 por R$ 1.500"), received_at=NOW + timedelta(milliseconds=100))
    h.clock.advance(1.5)
    await h.feed(m)
    [a] = h.stored()
    assert a.latency_telegram_ms == 1500
    assert a.latency_internal_ms == 1400


async def test_latency_is_clamped_to_zero_on_clock_skew() -> None:
    h = Harness()
    h.wish()
    m = replace(
        msg(text="RTX 4060 por R$ 1.500"),
        date=NOW + timedelta(seconds=5),
        received_at=NOW + timedelta(seconds=5),
    )
    await h.feed(m)
    [a] = h.stored()
    assert a.latency_telegram_ms == 0
    assert a.latency_internal_ms == 0


async def test_slow_notifier_does_not_delay_next_evaluation() -> None:
    h = Harness(FakeNotifier(delay_s=2))
    h.wish()
    await h.evaluator.on_received(MessageReceived(msg(1, text="RTX 4060 por R$ 1.500")))
    await h.evaluator.on_received(MessageReceived(msg(2, text="RTX 4060 por R$ 1.400")))
    assert len(h.stored()) == 2
    assert all(a.status is AlertStatus.pending for a in h.stored())
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current]
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


class FailingAdd(InMemoryAlertRepository):
    def __init__(self, bad_wish_id: int) -> None:
        super().__init__()
        self._bad = bad_wish_id

    def add(self, a: Alert) -> Alert:
        if a.wish_id == self._bad:
            raise RuntimeError("db down")
        return super().add(a)


async def test_failing_wish_does_not_block_other_wishes_and_leaves_message_unprocessed() -> None:
    h = Harness()
    h.alerts = FailingAdd(bad_wish_id=1)
    h.evaluator = Evaluator(
        wishes=WishlistApiReader(h.wishes),
        repo=h.alerts,
        cache=DedupCache(timedelta(minutes=30)),
        notifier=h.notifier,
        bus=h.bus,
        clock=h.clock,
        mark_processed=lambda c, m: h.processed.append((c, m)),
        channel_names=lambda: {10: "Promos"},
        sleep=h._no_sleep,
    )
    h.wish("RTX 4060", ("rtx 4060",))
    h.wish("Kit", ("ryzen",))
    await h.feed(msg(text="Kit Ryzen + RTX 4060 por R$ 1.500"))
    assert [a.wish_id for a in h.stored()] == [2]
    assert h.stored()[0].status is AlertStatus.sent
    assert h.notifier.calls == 1
    assert h.processed == []


async def test_notify_task_exception_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    h = Harness()
    h.wish()

    def boom() -> dict[int, str]:
        raise RuntimeError("names down")

    h.evaluator._channel_names = boom
    await h.feed(msg(text="RTX 4060 por R$ 1.500"))
    assert [a.status for a in h.stored()] == [AlertStatus.pending]
    assert any(r.message == "alert_notify_failed" for r in caplog.records)


async def test_concurrent_reposts_yield_one_alert() -> None:
    h = Harness()
    h.wish()
    a = msg(1, 10, "RTX 4060 por R$ 1.500")
    b = replace(msg(2, 20, "RTX 4060 por R$ 1.500"), fwd_from_channel_id=10, fwd_from_message_id=1)
    await asyncio.gather(
        h.evaluator.on_received(MessageReceived(a)), h.evaluator.on_received(MessageReceived(b))
    )
    await h.evaluator.wait_idle()
    assert len(h.stored()) == 1
    assert len(h.alerts.suppressions) == 1


LIST_POST = (
    "Leve 3 pelo preço de 2\n\n"
    "-12x NIVEA Derma Protect Clinical 150ml = R$ 87\nhttps://link.amazon/B06LZorOc\n\n"
    "-12x Rexona V8 Masculino 250ml = R$ 110\nhttps://link.amazon/B0fVH2s7r\n\n"
    "-12x Rexona Cotton Dry 250ml = R$ 117\nhttps://link.amazon/B0hk6Ou4C\n\n-Anúncio"
)


def _list_msg(text: str = LIST_POST) -> MessageData:
    links = tuple(x for x in text.split() if x.startswith("https://"))
    return replace(msg(text=text), links=links)


async def test_list_post_alerts_with_the_cheapest_matching_item_only() -> None:
    h = Harness()
    h.wish("Rexona", ("rexona",), 20000)
    await h.feed(_list_msg())
    [a] = h.stored()
    assert a.price_cents == 11000
    sent = h.notifier.sent[0]
    text = format_alert(sent)
    assert "Rexona V8" in text and "Rexona Cotton Dry" in text
    assert "NIVEA" not in text
    assert "https://link.amazon/B0fVH2s7r" in text


async def test_list_post_does_not_borrow_terms_across_items() -> None:
    h = Harness()
    h.wish("Mix", ("nivea", "rexona"), 20000)  # both words, but never in the same item
    await h.feed(_list_msg())
    assert h.stored() == []


async def test_list_post_respects_the_price_cap_of_the_matching_item() -> None:
    h = Harness()
    h.wish("Rexona", ("rexona",), 10000)  # the Rexona items cost 110 and 117
    await h.feed(_list_msg())
    assert h.stored() == []


async def test_list_post_item_inherits_the_header_terms() -> None:
    h = Harness()
    h.wish("Vaio", ("vaio",), 300000)
    text = (
        "Notebook VAIO FE16\n-Ryzen 3 = R$ 2374\nhttps://meli.la/1\n"
        "-Core i5 = R$ 2659\nhttps://meli.la/2"
    )
    await h.feed(_list_msg(text))
    [a] = h.stored()
    assert a.price_cents == 237400
