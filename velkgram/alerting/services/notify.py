"""Send an alert with bounded retries and a per-attempt timeout."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from velkgram.alerting.domain.models import AlertMessage
from velkgram.alerting.ports.notifier import NotConfigured, Notifier, NotifierError

log = logging.getLogger(__name__)


async def send_with_retry(
    notifier: Notifier,
    message: AlertMessage,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    delays: tuple[float, ...] = (1.0, 3.0),
    attempt_timeout: float = 1.5,
) -> tuple[bool, int, str | None]:
    """Return (ok, attempts, last_error); never raises."""
    last_error: str | None = None
    total = len(delays) + 1
    own = getattr(notifier, "attempt_timeout", None)
    timeout = own if isinstance(own, int | float) and not isinstance(own, bool) else attempt_timeout
    for attempt in range(1, total + 1):
        try:
            async with asyncio.timeout(timeout):
                await notifier.notify(message)
            return True, attempt, None
        except NotConfigured:
            return False, attempt, "no_chat"  # permanent until the user sets a chat
        except TimeoutError:
            last_error = f"timeout after {timeout}s"
        except NotifierError as exc:
            last_error = str(exc) or type(exc).__name__
        except Exception as exc:
            log.exception("notify_unexpected_error", extra={"attempt": attempt})
            last_error = f"{type(exc).__name__}: {exc}"
        log.warning("notify_attempt_failed", extra={"attempt": attempt, "error": last_error})
        if attempt < total:
            await sleep(delays[attempt - 1])
    return False, total, last_error
