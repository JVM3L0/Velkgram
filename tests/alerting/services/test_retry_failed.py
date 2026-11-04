from dataclasses import replace
from datetime import timedelta

from tests.fakes.clock import FakeClock
from tests.fakes.messages import NOW
from tests.fakes.notifier import FakeNotifier
from tests.fakes.repositories import InMemoryAlertRepository
from velkgram.alerting import Alert, AlertMessage, AlertStatus
from velkgram.alerting.domain.dedup import DedupCache, origin_key, price_key, rule_for_key
from velkgram.alerting.services.retry_failed import retry_failed, warm_cache


async def _no_sleep(_: float) -> None:
    return None


def _alert(status: AlertStatus, age: timedelta, attempts: int = 0) -> Alert:
    return Alert(
        id=None,
        wish_id=1,
        channel_id=10,
        message_id=5,
        price_cents=100000,
        price_unknown=False,
        dedup_keys=(origin_key(1, 10, 5, None, None), price_key(1, 100000)),
        status=status,
        attempts=attempts,
        delayed_minutes=None,
        created_at=NOW - age,
        sent_at=None,
        latency_telegram_ms=0,
        latency_internal_ms=0,
        last_error="x" if status is AlertStatus.failed else None,
    )


def _build(a: Alert) -> AlertMessage | None:
    return AlertMessage("w", "texto", a.price_cents, "Promos", None, None)


async def _run(repo: InMemoryAlertRepository, notifier: FakeNotifier) -> tuple[int, int]:
    return await retry_failed(repo, notifier, FakeClock(NOW), _build, sleep=_no_sleep)


async def test_failed_recent_is_retried_and_marked_sent() -> None:
    repo, notifier = InMemoryAlertRepository(), FakeNotifier()
    a = repo.add(_alert(AlertStatus.failed, timedelta(minutes=5), attempts=3))
    assert await _run(repo, notifier) == (1, 0)
    [got] = repo.list_since(NOW - timedelta(days=1))
    assert got.id == a.id
    assert got.status is AlertStatus.sent
    assert got.sent_at == NOW
    assert got.attempts == 4
    assert len(notifier.sent) == 1


async def test_failed_retry_that_fails_again_stays_failed() -> None:
    repo, notifier = InMemoryAlertRepository(), FakeNotifier(fail_times=99)
    repo.add(_alert(AlertStatus.failed, timedelta(minutes=5), attempts=3))
    assert await _run(repo, notifier) == (0, 0)
    [got] = repo.list_since(NOW - timedelta(days=1))
    assert got.status is AlertStatus.failed
    assert got.last_error is not None


async def test_failed_older_than_30min_expires() -> None:
    repo, notifier = InMemoryAlertRepository(), FakeNotifier()
    repo.add(_alert(AlertStatus.failed, timedelta(minutes=31)))
    assert await _run(repo, notifier) == (0, 1)
    [got] = repo.list_since(NOW - timedelta(days=1))
    assert got.status is AlertStatus.expired
    assert notifier.sent == []


async def test_stuck_pending_after_crash_is_retried() -> None:
    repo, notifier = InMemoryAlertRepository(), FakeNotifier()
    repo.add(_alert(AlertStatus.pending, timedelta(minutes=2)))
    old = repo.add(_alert(AlertStatus.pending, timedelta(hours=2)))
    repo.add(_alert(AlertStatus.pending, timedelta(seconds=5)))
    assert await _run(repo, notifier) == (1, 1)
    by_id = {a.id: a for a in repo.list_since(NOW - timedelta(days=1))}
    assert by_id[old.id].status is AlertStatus.expired
    assert sorted(a.status.value for a in by_id.values()) == ["expired", "pending", "sent"]


async def test_build_message_none_expires() -> None:
    repo, notifier = InMemoryAlertRepository(), FakeNotifier()
    repo.add(_alert(AlertStatus.failed, timedelta(minutes=1)))
    result = await retry_failed(repo, notifier, FakeClock(NOW), lambda _: None, sleep=_no_sleep)
    assert result == (0, 1)
    assert repo.list_since(NOW - timedelta(days=1))[0].status is AlertStatus.expired


def test_warm_cache_prevents_duplicate_after_restart() -> None:
    repo = InMemoryAlertRepository()
    a = repo.add(_alert(AlertStatus.sent, timedelta(minutes=10)))
    repo.add(replace(_alert(AlertStatus.sent, timedelta(minutes=45)), message_id=6))
    cache = DedupCache(timedelta(minutes=30))
    warm_cache(repo, cache, FakeClock(NOW))
    keys = [(rule_for_key(k), k) for k in a.dedup_keys]
    assert cache.find(keys, NOW) is not None
    assert cache.find(keys[1:], NOW) == (keys[1][0], a.id)
