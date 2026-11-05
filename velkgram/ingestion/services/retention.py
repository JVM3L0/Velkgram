"""Raw message text retention."""

from datetime import datetime

from velkgram.ingestion.ports.repository import MessageRepository


def purge_text_before(repo: MessageRepository, cutoff: datetime) -> int:
    """Blank message text older than `cutoff`; return the number of messages changed."""
    return repo.purge_text_before(cutoff)
