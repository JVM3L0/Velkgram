"""Alert persistence port."""

from datetime import datetime
from typing import Protocol

from velkgram.alerting.domain.models import Alert, SuppressionRule


class AlertRepository(Protocol):
    def add(self, a: Alert) -> Alert:
        """Store `a` and return it with its assigned id."""
        ...

    def update(self, a: Alert) -> None: ...

    def add_suppression(
        self,
        channel_id: int,
        message_id: int,
        wish_id: int,
        rule: SuppressionRule,
        matched_alert_id: int,
        at: datetime,
    ) -> None: ...

    def list_since(self, since: datetime) -> list[Alert]:
        """Alerts created at or after `since`, oldest first."""
        ...

    def list_retryable(self, since: datetime, stuck_before: datetime) -> list[Alert]:
        """`failed` alerts created at or after `since`, plus every `pending` alert created
        before `stuck_before` (crash leftovers, however old, so they can be retried or expired)."""
        ...

    def list_failed_before(self, before: datetime) -> list[Alert]:
        """`failed` alerts created before `before` (candidates for expiry)."""
        ...

    def has_alert_for_message(self, channel_id: int, message_id: int) -> bool: ...
