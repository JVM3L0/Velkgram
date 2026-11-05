"""Rebuild offers and retro matches from stored messages (idempotent)."""

from itertools import batched

from velkgram.offers.domain.models import MatchSource
from velkgram.offers.ports.messages import MessageSource
from velkgram.offers.services.build_offer import OfferBuilder


def rebuild_offers(source: MessageSource, builder: OfferBuilder, batch_size: int = 1000) -> int:
    """Re-ingest every stored message; return the number of offers built."""
    built = 0
    for batch in batched(source.iter_messages(), batch_size, strict=False):
        built += builder.ingest_many(batch, source=MatchSource.retro)
    return built
