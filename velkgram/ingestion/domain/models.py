"""Ingestion domain models."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ConnectionState = Literal["connected", "reconnecting", "fatal"]


@dataclass(frozen=True, slots=True)
class Heartbeat:
    last_seen: datetime
    connection_state: ConnectionState
    fatal_reason: str | None
    messages_seen: int
    alerts_sent: int
