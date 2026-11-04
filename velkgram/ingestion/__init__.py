"""Ingestion module public API (the SQLite adapters are wired by the apps)."""

from velkgram.ingestion.domain.models import ConnectionState, Heartbeat
from velkgram.ingestion.domain.sold_out import detect_sold_out
from velkgram.ingestion.ports.queries import DailyCount, IngestionQueries, MessageText
from velkgram.ingestion.ports.repository import MessageRepository

__all__ = [
    "ConnectionState",
    "DailyCount",
    "Heartbeat",
    "IngestionQueries",
    "MessageRepository",
    "MessageText",
    "detect_sold_out",
]
