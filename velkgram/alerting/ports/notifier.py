"""Outbound notification port."""

from typing import Protocol

from velkgram.alerting.domain.models import AlertMessage


class NotifierError(Exception):
    """Raised by a Notifier when delivery fails."""


class Notifier(Protocol):
    async def notify(self, message: AlertMessage) -> None: ...

    async def notify_system(self, text: str) -> None: ...


class NotConfigured(NotifierError):
    """The recipient has no chat to deliver to. Retrying cannot help, so it is never retried."""
