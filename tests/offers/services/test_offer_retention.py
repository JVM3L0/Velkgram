from datetime import UTC, datetime, timedelta

from tests.fakes.repositories import InMemoryOfferRepository
from velkgram.offers import purge_offer_text_before
from velkgram.offers.domain.build import offer_from_message
from velkgram.shared.events import MessageData

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def test_purge_offer_text_returns_count() -> None:
    repo = InMemoryOfferRepository()
    for mid, age in ((1, 100), (2, 95), (3, 1)):
        when = NOW - timedelta(days=age)
        m = MessageData(1, mid, when, when, "SSD 1TB R$ 300", (), None, None, None, False, "live")
        offer = offer_from_message(m, sold_out=False, deleted=False, now=NOW)
        assert offer is not None
        repo.upsert(offer)
    cutoff = NOW - timedelta(days=90)
    assert purge_offer_text_before(repo, cutoff) == 2
    assert purge_offer_text_before(repo, cutoff) == 0
