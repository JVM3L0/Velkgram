"""Alerting module public API (the SQLite adapters are wired by the apps)."""

from velkgram.alerting.domain.format import format_alert, format_brl, telegram_link
from velkgram.alerting.domain.models import (
    Alert,
    AlertKind,
    AlertMessage,
    AlertStatus,
    SuppressionRule,
)
from velkgram.alerting.ports.notifier import Notifier, NotifierError
from velkgram.alerting.ports.queries import (
    AlertQueries,
    DailyAlerts,
    DailySuppressions,
    LatencySample,
)
from velkgram.alerting.ports.repository import AlertRepository
from velkgram.alerting.services.notify import send_with_retry
from velkgram.shared.deals import extract_price

__all__ = [
    "Alert",
    "AlertKind",
    "AlertMessage",
    "AlertQueries",
    "AlertRepository",
    "AlertStatus",
    "DailyAlerts",
    "DailySuppressions",
    "LatencySample",
    "Notifier",
    "NotifierError",
    "SuppressionRule",
    "extract_price",
    "format_alert",
    "format_brl",
    "send_with_retry",
    "telegram_link",
]
