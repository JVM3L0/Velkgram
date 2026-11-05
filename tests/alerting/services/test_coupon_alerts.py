import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import timedelta

from tests.fakes.clock import FakeClock
from tests.fakes.messages import NOW
from tests.fakes.notifier import FakeNotifier
from tests.fakes.repositories import FakeWishReader, InMemoryAlertRepository
from velkgram.alerting import Alert, AlertKind, AlertMessage, AlertStatus
from velkgram.alerting.domain.dedup import DedupCache
from velkgram.alerting.domain.models import SuppressionRule, WishView
from velkgram.alerting.services.coupon_alerts import CouponAlerter
from velkgram.alerting.services.retry_failed import retry_failed
from velkgram.shared.events import CouponMatchedWish, CouponTargetData

CH = -1001234567890
LINK = "https://s.shopee.com.br/70GSVaUJxC"


async def _no_sleep(_: float) -> None:
    return None


def _wish(id: int, name: str = "SSD") -> WishView:
    return WishView(id, name, (("ssd",),), (), 20000)


def _target(wish_id: int, **kw: object) -> CouponTargetData:
    base = CouponTargetData(
        wish_id=wish_id,
        offer_channel_id=CH,
        offer_message_id=10,
        offer_price_cents=9900,
        over_max=False,
        discount="R$ 10 OFF",
        min_cents=4000,
        codes=("QIP98Q1ZXO",),
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def _event(*targets: CouponTargetData, **kw: object) -> CouponMatchedWish:
    base = CouponMatchedWish(
        coupon_channel_id=CH,
        coupon_message_id=50,
        coupon_origin_channel_id=None,
        coupon_origin_message_id=None,
        coupon_posted_at=NOW - timedelta(seconds=5),
        coupon_received_at=NOW - timedelta(seconds=4),
        store="Shopee",
        scope=None,
        link=LINK,
        targets=targets,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


class Harness:
    def __init__(self, notifier: FakeNotifier | None = None) -> None:
        self.wishes = FakeWishReader()
        self.wishes.views = [_wish(1), _wish(2, "Teclado")]
        self.wishes.enabled_ids = {1, 2}
        self.repo = InMemoryAlertRepository()
        self.notifier = notifier or FakeNotifier()
        self.clock = FakeClock(NOW)
        self.cache = DedupCache(
            timedelta(minutes=30), {SuppressionRule.wish_coupon: timedelta(days=3)}
        )
        self.alerter = CouponAlerter(
            self.wishes, self.repo, self.cache, self.notifier, self.clock, sleep=_no_sleep
        )

    async def feed(self, e: CouponMatchedWish) -> None:
        await self.alerter.on_coupon(e)
        await self.alerter.drain()

    def alerts(self) -> list[Alert]:
        return self.repo.list_since(NOW - timedelta(days=30))


async def test_one_event_with_two_targets_gives_two_alerts() -> None:
    h = Harness()
    await h.feed(_event(_target(1), _target(2)))
    alerts = h.alerts()
    assert len(alerts) == 2
    assert len(h.notifier.sent) == 2
    a = alerts[0]
    assert a.kind is AlertKind.coupon
    assert a.status is AlertStatus.sent
    assert (a.channel_id, a.message_id, a.price_cents) == (CH, 50, 9900)
    assert (a.offer_channel_id, a.offer_message_id, a.over_max) == (CH, 10, False)
    assert a.delayed_minutes is None
    assert a.latency_telegram_ms == 1000
    assert a.dedup_keys == (f"wco:1:{CH}:50", "wcc:1:Shopee:QIP98Q1ZXO")
    assert a.payload is not None
    assert a.payload.splitlines()[1] == 'Para "SSD": oferta de R$ 99,00'
    assert h.notifier.sent[0].rendered == a.payload


async def test_link_falls_back_to_the_telegram_post() -> None:
    h = Harness()
    await h.feed(_event(_target(1), link=None))
    payload = h.alerts()[0].payload
    assert payload is not None
    assert payload.splitlines()[-1] == f"https://t.me/c/{str(CH)[4:]}/50"


async def test_edited_coupon_within_three_days_gives_no_second_alert() -> None:
    h = Harness()
    await h.feed(_event(_target(1)))
    h.clock.advance(2 * 24 * 3600)
    await h.feed(_event(_target(1, offer_price_cents=8000)))
    assert len(h.alerts()) == 1
    assert h.repo.suppressions[0][3] == "wish_coupon"


async def test_same_codes_from_another_channel_are_suppressed_by_content_key() -> None:
    h = Harness()
    await h.feed(_event(_target(1)))
    await h.feed(_event(_target(1), coupon_channel_id=-1009999999999, coupon_message_id=7))
    assert len(h.alerts()) == 1
    assert len(h.repo.suppressions) == 1


async def test_forward_of_an_alerted_coupon_is_suppressed_by_origin_key() -> None:
    h = Harness()
    await h.feed(_event(_target(1)))
    fwd = _event(
        _target(1, codes=("OTHER",)),
        coupon_channel_id=-1009999999999,
        coupon_message_id=7,
        coupon_origin_channel_id=CH,
        coupon_origin_message_id=50,
    )
    await h.feed(fwd)
    assert len(h.alerts()) == 1
    assert len(h.repo.suppressions) == 1


async def test_disabled_wish_gives_no_alert() -> None:
    h = Harness()
    h.wishes.enabled_ids = {2}
    await h.feed(_event(_target(1), _target(2)))
    assert [a.wish_id for a in h.alerts()] == [2]


async def test_over_max_target_says_so() -> None:
    h = Harness()
    await h.feed(_event(_target(1, over_max=True, offer_price_cents=25000)))
    a = h.alerts()[0]
    assert a.over_max
    assert a.payload is not None
    assert "(acima do seu limite de R$ 200,00)" in a.payload


async def test_on_coupon_returns_before_the_notifier_is_called() -> None:
    release = asyncio.Event()

    class Blocking(FakeNotifier):
        async def notify(self, message: AlertMessage) -> None:
            await release.wait()
            await super().notify(message)

    h = Harness(Blocking())
    task = asyncio.create_task(h.alerter.run())
    await asyncio.wait_for(h.alerter.on_coupon(_event(_target(1))), timeout=1)
    assert h.notifier.calls == 0
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(h.alerter.drain(), timeout=1)
    assert len(h.notifier.sent) == 1
    await h.alerter.stop()
    assert task.done()


async def test_one_failing_target_does_not_stop_the_others() -> None:
    h = Harness()
    original = h.repo.add
    calls = 0

    def flaky(a: Alert) -> Alert:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("db")
        return original(a)

    h.repo.add = flaky  # type: ignore[method-assign]
    await h.feed(_event(_target(1), _target(2)))
    assert [a.wish_id for a in h.alerts()] == [2]


async def test_purged_coupon_alert_is_retried_from_its_payload() -> None:
    h = Harness(FakeNotifier(fail_times=3))
    await h.feed(_event(_target(1)))
    [failed] = h.alerts()
    assert failed.status is AlertStatus.failed
    assert failed.payload is not None
    payload = failed.payload

    def build(a: Alert) -> AlertMessage | None:
        assert a.kind is AlertKind.coupon  # no stored message or channel to read
        return AlertMessage("", "", a.price_cents, "", None, None, rendered=a.payload)

    sleep: Callable[[float], Awaitable[None]] = _no_sleep
    sent, expired = await retry_failed(h.repo, h.notifier, h.clock, build, sleep=sleep)
    assert (sent, expired) == (1, 0)
    assert h.notifier.sent[-1].rendered == payload
    assert h.alerts()[0].status is AlertStatus.sent


async def test_a_later_edit_can_alert_once_after_a_v1_alert_with_a_coupon_line() -> None:
    # Accepted: a v1 alert that already carried a coupon line does not block the coupon alert.
    h = Harness()
    h.repo.add(
        Alert(
            id=None,
            wish_id=1,
            channel_id=CH,
            message_id=10,
            price_cents=9900,
            price_unknown=False,
            dedup_keys=(f"org:1:{CH}:10", "wp:1:9900"),
            status=AlertStatus.sent,
            attempts=1,
            delayed_minutes=None,
            created_at=NOW,
            sent_at=NOW,
            latency_telegram_ms=0,
            latency_internal_ms=0,
            last_error=None,
        )
    )
    await h.feed(_event(_target(1)))
    await h.feed(_event(_target(1), coupon_message_id=51))
    coupons = [a for a in h.alerts() if a.kind is AlertKind.coupon]
    assert len(coupons) == 1
