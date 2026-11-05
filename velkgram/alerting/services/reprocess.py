"""Startup reprocessing of messages stored but never evaluated (crash recovery)."""

from collections.abc import Callable
from datetime import datetime, timedelta

from velkgram.alerting.services.evaluate import Evaluator
from velkgram.shared.events import MessageData, MessageReceived
from velkgram.shared.ports import Clock

_MAX_AGE = timedelta(minutes=30)


async def reprocess_unprocessed(
    list_unprocessed: Callable[[datetime], list[MessageData]],
    evaluator: Evaluator,
    clock: Clock,
) -> int:
    """Feed recent unprocessed messages through the evaluator; return how many."""
    since = clock.now() - _MAX_AGE
    messages = [m for m in list_unprocessed(since) if m.received_at >= since]
    for m in messages:
        await evaluator.on_received(MessageReceived(m))
    await evaluator.wait_idle()
    return len(messages)
