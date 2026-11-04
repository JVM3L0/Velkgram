"""Recovery paths: retry failed/stuck alerts, expire old ones, warm the dedup cache."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import timedelta

from velkgram.alerting.domain.dedup import DedupCache, rule_for_key
from velkgram.alerting.domain.models import Alert, AlertMessage, AlertStatus
from velkgram.alerting.ports.notifier import Notifier
from velkgram.alerting.ports.repository import AlertRepository
from velkgram.alerting.services.notify import send_with_retry
from velkgram.shared.ports import Clock

log = logging.getLogger(__name__)

_MAX_AGE = timedelta(minutes=30)
_STUCK_AFTER = timedelta(seconds=15)


async def retry_failed(
    repo: AlertRepository,
    notifier: Notifier,
    clock: Clock,
    build_message: Callable[[Alert], AlertMessage | None],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_alert_sent: Callable[[], None] = lambda: None,
) -> tuple[int, int]:
    """Retry recent failed/stuck alerts and expire old ones; return (sent, expired)."""
    now = clock.now()
    cutoff = now - _MAX_AGE
    candidates = {
        a.id: a
        for a in (
            *repo.list_retryable(since=cutoff, stuck_before=now - _STUCK_AFTER),
            *repo.list_failed_before(cutoff),
        )
        if a.id is not None
    }
    sent = expired = 0
    for alert in sorted(candidates.values(), key=lambda a: (a.created_at, a.id or 0)):
        try:
            message = None if alert.created_at < cutoff else build_message(alert)
            if message is None:
                repo.update(replace(alert, status=AlertStatus.expired))
                expired += 1
                continue
            ok, attempts, error = await send_with_retry(notifier, message, sleep=sleep)
            repo.update(
                replace(
                    alert,
                    status=AlertStatus.sent if ok else AlertStatus.failed,
                    attempts=alert.attempts + attempts,
                    sent_at=now if ok else alert.sent_at,
                    last_error=error,
                )
            )
        except Exception:
            log.exception("alert_retry_failed", extra={"alert_id": alert.id})
            continue
        if ok:
            sent += 1
            on_alert_sent()
    return sent, expired


def warm_cache(repo: AlertRepository, cache: DedupCache, clock: Clock) -> None:
    """Remember keys of recent alerts so a restart does not re-alert."""
    for alert in repo.list_since(clock.now() - _MAX_AGE):
        if alert.id is None:
            continue
        cache.remember([(rule_for_key(k), k) for k in alert.dedup_keys], alert.id, alert.created_at)
