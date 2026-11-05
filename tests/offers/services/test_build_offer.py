import logging
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.repositories import FakeWishReader, InMemoryOfferRepository
from velkgram.offers.domain.models import MatchSource
from velkgram.offers.services.build_offer import OfferBuilder
from velkgram.shared.deals import WishView
from velkgram.shared.events import MessageData, MessageDeleted, MessageEdited, MessageReceived

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _msg(text: str = "SSD Kingston 1TB por R$ 299,90", **kw: object) -> MessageData:
    base = MessageData(
        channel_id=1,
        message_id=2,
        date=datetime(2026, 11, 4, 11, 0, tzinfo=UTC),
        received_at=NOW,
        text=text,
        links=("https://amzn.to/x",),
        fwd_from_channel_id=None,
        fwd_from_message_id=None,
        grouped_id=None,
        has_photo=True,
        source="live",
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def _wish(wish_id: int = 1, max_price: int = 30000, **kw: object) -> WishView:
    base = WishView(
        id=wish_id, name="ssd", required=(("ssd",),), excluded=(), max_price_cents=max_price
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def _edited(m: MessageData, sold_out_hint: bool = False) -> MessageEdited:
    return MessageEdited(message=m, version=1, edited_at=NOW, sold_out_hint=sold_out_hint)


@pytest.fixture
def repo() -> InMemoryOfferRepository:
    return InMemoryOfferRepository()


@pytest.fixture
def wishes() -> FakeWishReader:
    w = FakeWishReader()
    w.views = [_wish()]
    w.enabled_ids = {1}
    return w


@pytest.fixture
def builder(repo: InMemoryOfferRepository, wishes: FakeWishReader) -> OfferBuilder:
    return OfferBuilder(repo, wishes, FakeClock(NOW))


def _match_sources(repo: InMemoryOfferRepository) -> list[tuple[int, MatchSource]]:
    return [(m.wish_id, m.source) for m in repo._matches.values()]


async def test_received_creates_offer_and_live_match(
    builder: OfferBuilder, repo: InMemoryOfferRepository
) -> None:
    await builder.on_received(MessageReceived(_msg()))
    await builder.drain()
    offer = repo.get(1, 2)
    assert offer is not None
    assert offer.price_cents == 29990
    assert _match_sources(repo) == [(1, MatchSource.live)]


async def test_match_respects_max_price_and_unknown_price(
    builder: OfferBuilder, repo: InMemoryOfferRepository
) -> None:
    assert builder.ingest(_msg("SSD caro por R$ 500,00", message_id=3))
    assert builder.ingest(_msg("SSD sem preco", message_id=4))
    keys = {(m.message_id) for m in repo._matches.values()}
    assert keys == {4}


async def test_disabled_wish_matches_for_history(
    builder: OfferBuilder, repo: InMemoryOfferRepository, wishes: FakeWishReader
) -> None:
    wishes.enabled_ids = set()
    builder.ingest(_msg())
    assert _match_sources(repo) == [(1, MatchSource.live)]


async def test_forward_keeps_origin_ids(
    builder: OfferBuilder, repo: InMemoryOfferRepository
) -> None:
    builder.ingest(_msg(fwd_from_channel_id=77, fwd_from_message_id=88))
    offer = repo.get(1, 2)
    assert offer is not None
    assert (offer.origin_channel_id, offer.origin_message_id) == (77, 88)


async def test_backfill_source_still_gets_live_matches(
    builder: OfferBuilder, repo: InMemoryOfferRepository
) -> None:
    builder.ingest(_msg(source="backfill"))
    assert _match_sources(repo) == [(1, MatchSource.live)]


async def test_edit_updates_price_and_sets_sold_out(
    builder: OfferBuilder, repo: InMemoryOfferRepository
) -> None:
    builder.ingest(_msg())
    await builder.on_edited(_edited(_msg("SSD Kingston 1TB por R$ 250,00"), sold_out_hint=True))
    await builder.drain()
    offer = repo.get(1, 2)
    assert offer is not None
    assert offer.price_cents == 25000
    assert offer.sold_out is True


async def test_edit_never_removes_existing_match(
    builder: OfferBuilder, repo: InMemoryOfferRepository
) -> None:
    builder.ingest(_msg())
    await builder.on_edited(_edited(_msg("Agora e outra coisa: teclado")))
    await builder.drain()
    assert len(repo._matches) == 1


async def test_delete_marks_offer_deleted(
    builder: OfferBuilder, repo: InMemoryOfferRepository
) -> None:
    builder.ingest(_msg())
    await builder.on_deleted(MessageDeleted(channel_id=1, message_ids=(2,), deleted_at=NOW))
    await builder.drain()
    offer = repo.get(1, 2)
    assert offer is not None
    assert offer.deleted is True


async def test_handlers_only_enqueue(builder: OfferBuilder, repo: InMemoryOfferRepository) -> None:
    await builder.on_received(MessageReceived(_msg()))
    assert repo.get(1, 2) is None
    await builder.drain()
    assert repo.get(1, 2) is not None


async def test_edit_without_previous_offer_builds_fresh_offer(
    builder: OfferBuilder, repo: InMemoryOfferRepository
) -> None:
    await builder.on_edited(_edited(_msg(), sold_out_hint=True))
    await builder.drain()
    offer = repo.get(1, 2)
    assert offer is not None
    assert offer.sold_out is True
    assert offer.deleted is False
    assert len(repo._matches) == 1


async def test_edit_keeps_deleted_flag(
    builder: OfferBuilder, repo: InMemoryOfferRepository
) -> None:
    builder.ingest(_msg())
    repo.mark_deleted(1, [2], NOW)
    await builder.on_edited(_edited(_msg("SSD Kingston 1TB por R$ 250,00")))
    await builder.drain()
    offer = repo.get(1, 2)
    assert offer is not None
    assert offer.deleted is True
    assert offer.price_cents == 25000


async def test_edit_to_blank_text_keeps_title_and_price(
    builder: OfferBuilder, repo: InMemoryOfferRepository
) -> None:
    builder.ingest(_msg())
    before = repo.get(1, 2)
    assert before is not None
    await builder.on_edited(_edited(_msg(""), sold_out_hint=True))
    await builder.drain()
    after = repo.get(1, 2)
    assert after is not None
    assert (after.title, after.price_cents, after.text) == (
        before.title,
        before.price_cents,
        before.text,
    )
    assert after.sold_out is True


async def test_link_only_offer_gets_no_matches(
    builder: OfferBuilder, repo: InMemoryOfferRepository
) -> None:
    assert builder.ingest(_msg(""))
    offer = repo.get(1, 2)
    assert offer is not None
    assert offer.text is None
    assert repo._matches == {}


async def test_repository_error_is_logged_not_raised(
    builder: OfferBuilder, repo: InMemoryOfferRepository, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(_o: object) -> None:
        raise RuntimeError("db down")

    repo.upsert = boom  # type: ignore[method-assign]
    await builder.on_received(MessageReceived(_msg()))
    with caplog.at_level(logging.ERROR):
        await builder.drain()
    assert any("offer_build_failed" in r.getMessage() for r in caplog.records)


async def test_message_without_text_or_links_is_ignored(
    builder: OfferBuilder, repo: InMemoryOfferRepository
) -> None:
    assert builder.ingest(_msg("", links=())) is False
    assert repo.get(1, 2) is None


async def test_blank_text_on_existing_offer_only_updates_flags(
    builder: OfferBuilder, repo: InMemoryOfferRepository
) -> None:
    builder.ingest(_msg())
    before = repo.get(1, 2)
    assert before is not None
    assert builder.ingest(_msg(""), sold_out=True)
    after = repo.get(1, 2)
    assert after is not None
    assert after.sold_out is True
    assert after.text == before.text
    assert after.title == before.title
    assert len(repo._matches) == 1
