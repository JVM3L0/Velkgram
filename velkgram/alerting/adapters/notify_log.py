"""Notifier that only logs (dev/fallback adapter)."""

import logging

from velkgram.alerting.domain.format import format_alert
from velkgram.alerting.domain.models import AlertMessage

log = logging.getLogger(__name__)


class LogNotifier:
    async def notify(self, message: AlertMessage) -> None:
        log.info("alert_notified", extra={"text": format_alert(message)})

    async def notify_system(self, text: str) -> None:
        log.info("system_notified", extra={"text": text})
