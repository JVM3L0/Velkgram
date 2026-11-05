"""Offer text retention."""

from datetime import datetime

from velkgram.offers.ports.repository import OfferRepository


def purge_offer_text_before(repo: OfferRepository, cutoff: datetime) -> int:
    """Blank offer text older than `cutoff`; return the number of offers changed."""
    return repo.purge_text_before(cutoff)
