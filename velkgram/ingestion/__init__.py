"""Ingestion module public API (the SQLite adapters are wired by the apps)."""

from velkgram.ingestion.domain.models import ConnectionState, Heartbeat
from velkgram.ingestion.domain.sold_out import detect_sold_out
from velkgram.ingestion.ports.queries import (
    DailyCount,
    IngestionQueries,
    MessageText,
    StoredMessage,
)
from velkgram.ingestion.ports.repository import MessageRepository
from velkgram.ingestion.ports.telegram import (
    ChannelResolutionError,
    ResolvedChannel,
    TelegramDeferred,
    TelegramGateway,
)
from velkgram.ingestion.services.backfill import backfill_all, backfill_channel, snapshot_cursors
from velkgram.ingestion.services.connection import ConnectionWatcher
from velkgram.ingestion.services.gap_check import gap_check
from velkgram.ingestion.services.heartbeat import HeartbeatWriter
from velkgram.ingestion.services.ingest import Ingestor
from velkgram.ingestion.services.retention import purge_text_before

__all__ = [
    "ChannelResolutionError",
    "ConnectionState",
    "ConnectionWatcher",
    "DailyCount",
    "Heartbeat",
    "HeartbeatWriter",
    "IngestionQueries",
    "Ingestor",
    "MessageRepository",
    "MessageText",
    "ResolvedChannel",
    "StoredMessage",
    "TelegramDeferred",
    "TelegramGateway",
    "backfill_all",
    "backfill_channel",
    "detect_sold_out",
    "gap_check",
    "purge_text_before",
    "snapshot_cursors",
]
