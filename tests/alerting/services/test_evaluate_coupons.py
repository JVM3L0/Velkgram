import asyncio
import logging
from datetime import timedelta

import pytest

from tests.fakes.active_coupons import FakeActiveCoupons
from tests.fakes.clock import FakeClock
from tests.fakes.messages import NOW, msg
from tests.fakes.notifier import FakeNotifier
from tests.fakes.repositories import InMemoryAlertRepository, InMemoryWishRepository
from velkgram.alerting import Alert
from velkgram.alerting.adapters.wishlist_api import WishlistApiReader
from velkgram.alerting.domain.dedup import DedupCache
from velkgram.alerting.domain.models import ActiveCoupon
from velkgram.alerting.services.evaluate import Evaluator
from velkgram.offers import classify_message
from velkgram.shared.adapters.bus_memory import MemoryBus
from velkgram.shared.events import MessageData, MessageReceived
from velkgram.wishlist import Wish

CH = 10


def _coupon(
    message_id: int, codes: tuple[str, ...] = ("QIP98Q1ZXO",), **kw: object
) -> ActiveCoupon:
    base = {
        "channel_id": CH,
        "message_id": message_id,
        "posted_at": NOW - timedelta(hours=1),
        "discount": "R$ 10 OFF",
        "min_cents": 4000,
        "codes": codes,
    }
    base.update(kw)
    return ActiveCoupon(**base)  # type: ignore[arg-type]


async def _no_sleep(_: float) -> None:
    return None


class Harness:
    def __init__(
        self,
        coupons: FakeActiveCoupons | None,
        store: str | None = "shopee",
        is_coupon_post: bool = False,
        notifier: FakeNotifier | None = None,
    ) -> None:
        self.wishes = InMemoryWishRepository()
        self.alerts = InMemoryAlertRepository()
        self.notifier = notifier or FakeNotifier()
        self.clock = FakeClock(NOW)
        self.bus = MemoryBus()
        self.processed: list[tuple[int, int]] = []
        self.evaluator = Evaluator(
            wishes=WishlistApiReader(self.wishes),
            repo=self.alerts,
            cache=DedupCache(timedelta(minutes=30)),
            notifier=self.notifier,
            bus=self.bus,
            clock=self.clock,
            mark_processed=lambda c, m: self.processed.append((c, m)),
            channel_names=lambda: {CH: "Promos"},
            sleep=_no_sleep,
            coupons=coupons,
            classify=lambda _m: (store, is_coupon_post),
        )

    def wish(self, name: str = "RTX 4060", max_cents: int = 100000) -> None:
        self.wishes.add(Wish(None, name, ("rtx 4060",), (), max_cents, True))

    async def feed(self, m: MessageData) -> None:
        await self.evaluator.on_received(MessageReceived(m))
        await self.evaluator.wait_idle()

    def stored(self) -> list[Alert]:
        return self.alerts.list_since(NOW - timedelta(days=1))


OVER = "RTX 4060 por R$ 1.200,00"  # above a R$ 1.000 max, within 1.5x
UNDER = "RTX 4060 por R$ 900,00"


async def test_over_max_with_applicable_coupon_alerts_with_suffix() -> None:
    port = FakeActiveCoupons([_coupon(5)])
    h = Harness(port)
    h.wish()
    await h.feed(msg(7, text=OVER))
    [a] = h.stored()
    assert a.over_max
    assert a.price_cents == 120000
    sent = h.notifier.sent[0]
    assert sent.over_max_cents == 100000
    # the over-max lookup uses the message price, a 24 h window and excludes the message itself
    store, since, price, exclude = port.calls[0]
    assert (store, since, price, exclude) == ("shopee", NOW - timedelta(hours=24), 120000, (CH, 7))


async def test_over_max_without_coupon_does_not_alert() -> None:
    h = Harness(FakeActiveCoupons([]))
    h.wish()
    await h.feed(msg(7, text=OVER))
    assert h.stored() == []
    assert h.processed == [(CH, 7)]


async def test_above_the_ceiling_does_not_alert_nor_call_the_port() -> None:
    port = FakeActiveCoupons([_coupon(5)])
    h = Harness(port)
    h.wish()
    await h.feed(msg(7, text="RTX 4060 por R$ 1.600,00"))
    assert h.stored() == []
    assert port.calls == []


async def test_coupon_post_never_takes_over_max_path_nor_gets_lines() -> None:
    port = FakeActiveCoupons([_coupon(5)])
    h = Harness(port, is_coupon_post=True)
    h.wish(max_cents=200000)
    await h.feed(msg(7, text="Cupom RTX 4060 acima de R$ 1.500"))  # no price over max
    h.wish("Outra", max_cents=100000)
    await h.feed(msg(8, text=OVER))
    assert port.calls == []
    assert all(s.coupon_lines == () and s.over_max_cents is None for s in h.notifier.sent)


async def test_real_classifier_treats_coupon_post_as_coupon() -> None:
    m = msg(text="Cupom Shopee\n\nR$ 10 OFF em R$ 40: QIP98Q1ZXO")
    assert classify_message(m).is_coupon_post


async def test_port_error_in_evaluate_keeps_v1_behavior_and_complete() -> None:
    h = Harness(FakeActiveCoupons(error=RuntimeError("db locked")))
    h.wish()
    await h.feed(msg(7, text=OVER))
    assert h.stored() == []
    assert h.processed == [(CH, 7)]  # complete stays true


async def test_port_error_in_notify_sends_without_lines() -> None:
    h = Harness(FakeActiveCoupons(error=RuntimeError("db locked")))
    h.wish()
    await h.feed(msg(7, text=UNDER))
    [a] = h.stored()
    assert a.status.value == "sent"
    assert h.notifier.sent[0].coupon_lines == ()
    assert h.processed == [(CH, 7)]


async def test_alert_under_max_gets_at_most_two_lines_newest_first() -> None:
    coupons = [_coupon(3, ("AAA",)), _coupon(2, ("BBB", "CCC")), _coupon(1, ("DDD",))]
    port = FakeActiveCoupons(coupons)
    h = Harness(port)
    h.wish()
    await h.feed(msg(7, text=UNDER))
    lines = h.notifier.sent[0].coupon_lines
    assert lines == (
        "🎟️ Cupom ativo da loja: AAA — R$ 10 OFF a partir de R$ 40,00",
        "🎟️ Cupom ativo da loja: BBB, CCC — R$ 10 OFF a partir de R$ 40,00",
    )
    assert h.notifier.sent[0].over_max_cents is None
    assert port.calls[0][2:] == (90000, (CH, 7))


async def test_unknown_price_gets_no_lines_and_no_call() -> None:
    port = FakeActiveCoupons([_coupon(5)])
    h = Harness(port)
    h.wish()
    await h.feed(msg(7, text="Corre! RTX 4060 com desconto"))
    assert port.calls == []
    assert h.notifier.sent[0].coupon_lines == ()


async def test_no_store_means_no_lookup() -> None:
    port = FakeActiveCoupons([_coupon(5)])
    h = Harness(port, store=None)
    h.wish()
    await h.feed(msg(7, text=UNDER))
    await h.feed(msg(8, text=OVER))
    assert port.calls == []
    assert len(h.notifier.sent) == 1


async def test_three_wishes_one_message_one_lookup_each_site() -> None:
    port = FakeActiveCoupons([_coupon(5)])
    h = Harness(port)
    for n in ("A", "B", "C"):
        h.wish(n)
    await h.feed(msg(7, text=UNDER))
    assert len(h.notifier.sent) == 3
    assert len(port.calls) == 1  # notify side shares one lookup; _evaluate made none
    await h.feed(msg(8, text=OVER))
    assert len(h.notifier.sent) == 6
    assert len(port.calls) == 3  # _evaluate once + notify side once for the new price
    assert all(s.over_max_cents == 100000 for s in h.notifier.sent[3:])


async def test_without_a_port_v1_is_unchanged() -> None:
    h = Harness(None)
    h.wish()
    await h.feed(msg(7, text=UNDER))
    await h.feed(msg(8, text=OVER))
    assert len(h.notifier.sent) == 1


async def test_notifier_runs_only_after_the_slow_port_returns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    notifier = FakeNotifier()
    port = FakeActiveCoupons([_coupon(5)], delay_s=0.06)
    h = Harness(port, notifier=notifier)
    h.wish()
    with caplog.at_level(logging.WARNING):
        await h.evaluator.on_received(MessageReceived(msg(7, text=UNDER)))
        assert notifier.calls == 0  # nothing was sent while the port was still running
        await h.evaluator.wait_idle()
    assert notifier.calls == 1
    assert any(r.message == "active_coupons_slow" for r in caplog.records)


async def test_port_failure_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    h = Harness(FakeActiveCoupons(error=RuntimeError("x")))
    h.wish()
    with caplog.at_level(logging.WARNING):
        await h.feed(msg(7, text=OVER))
    assert any(r.message == "active_coupons_failed" for r in caplog.records)
    await asyncio.sleep(0)
