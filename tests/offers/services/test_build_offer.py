import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.repositories import FakeMessageSource, FakeWishReader, InMemoryOfferRepository
from velkgram.offers.domain.models import MatchSource, OfferMatch
from velkgram.offers.ports.messages import SourceMessage
from velkgram.offers.services.build_offer import OfferBuilder
from velkgram.offers.services.rebuild import rebuild_offers
from velkgram.shared.deals import WishView
from velkgram.shared.events import (
    CouponMatchedWish,
    Event,
    MessageData,
    MessageDeleted,
    MessageEdited,
    MessageReceived,
)

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


async def test_blank_redelivery_never_clears_flags(
    builder: OfferBuilder, repo: InMemoryOfferRepository
) -> None:
    builder.ingest(_msg(), sold_out=True, deleted=True)
    builder.ingest(_msg(""))
    after = repo.get(1, 2)
    assert after is not None
    assert after.sold_out is True
    assert after.deleted is True


async def test_blank_redelivery_of_unpurged_offer_adds_no_matches(
    builder: OfferBuilder, repo: InMemoryOfferRepository, wishes: FakeWishReader
) -> None:
    builder.ingest(_msg())
    before = len(repo._matches)
    wishes.views = [*wishes.views, WishView(99, "x", (("ssd",),), (), 10_000_000)]
    builder.ingest(_msg(""))
    assert len(repo._matches) == before


async def test_coupon_post_never_matches_a_wish(
    builder: OfferBuilder, repo: InMemoryOfferRepository, wishes: FakeWishReader
) -> None:
    """A coupon post lists many products; matching its text would put it in the wish history."""
    wishes.views = [_wish(required=(("cupom",),), max_price_cents=10_000_000)]
    builder.ingest(_coupon_msg())
    assert repo.get(1, 50) is not None
    assert repo._matches == {}


# --- coupon events ----------------------------------------------------------------------------

SHOPEE_COUPON = (
    "Cupom Shopee\n\nR$ 10 OFF em R$ 40: QIP98Q1ZXO\n\n-Resgate aqui: \n"
    "https://s.shopee.com.br/70GSVaUJxC\n\n-Link carrinho:\n"
    "https://s.shopee.com.br/7fW9IpEnZG\n\n-Anúncio"
)
COUPON_LINKS = ("https://s.shopee.com.br/70GSVaUJxC", "https://s.shopee.com.br/7fW9IpEnZG")


def _coupon_msg(**kw: object) -> MessageData:
    return _msg(
        SHOPEE_COUPON,
        message_id=50,
        date=NOW - timedelta(minutes=5),
        links=COUPON_LINKS,
        **kw,
    )


def _product_msg(message_id: int, text: str = "SSD Kingston 1TB por R$ 99") -> MessageData:
    return _msg(
        text,
        message_id=message_id,
        date=NOW - timedelta(hours=2),
        links=("https://s.shopee.com.br/prod",),
    )


class Published:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self.fail = False

    async def __call__(self, e: Event) -> None:
        if self.fail:
            raise RuntimeError("bus down")
        self.events.append(e)


@pytest.fixture
def published() -> Published:
    return Published()


@pytest.fixture
def pub_builder(
    repo: InMemoryOfferRepository, wishes: FakeWishReader, published: Published
) -> OfferBuilder:
    wishes.views = [_wish(1, 20000), _wish(2, 20000)]
    wishes.enabled_ids = {1, 2}
    b = OfferBuilder(repo, wishes, FakeClock(NOW), publish=published)
    b.ingest(_product_msg(10), source=MatchSource.retro)
    return b


async def _feed(b: OfferBuilder, m: MessageData) -> None:
    await b.on_received(MessageReceived(m))
    await b.drain()


async def test_live_coupon_publishes_one_event_with_every_target(
    pub_builder: OfferBuilder, published: Published
) -> None:
    await _feed(pub_builder, _coupon_msg())
    [event] = published.events
    assert isinstance(event, CouponMatchedWish)
    assert (event.coupon_channel_id, event.coupon_message_id) == (1, 50)
    assert event.store == "shopee"
    assert event.store_title == "Shopee"
    assert event.link == "https://s.shopee.com.br/70GSVaUJxC"
    assert event.coupon_posted_at == NOW - timedelta(minutes=5)
    assert event.coupon_received_at == NOW
    assert (event.coupon_origin_channel_id, event.coupon_origin_message_id) == (None, None)
    assert [t.wish_id for t in event.targets] == [1, 2]
    assert event.targets[0].codes == ("QIP98Q1ZXO",)


async def test_forwarded_live_coupon_publishes_with_its_origin(
    pub_builder: OfferBuilder, published: Published
) -> None:
    await _feed(pub_builder, _coupon_msg(fwd_from_channel_id=77, fwd_from_message_id=88))
    [event] = published.events
    assert isinstance(event, CouponMatchedWish)
    assert (event.coupon_origin_channel_id, event.coupon_origin_message_id) == (77, 88)


async def test_edit_republishes(pub_builder: OfferBuilder, published: Published) -> None:
    await _feed(pub_builder, _coupon_msg())
    await pub_builder.on_edited(_edited(_coupon_msg()))
    await pub_builder.drain()
    assert len(published.events) == 2


async def test_disabled_wish_is_not_a_target(
    pub_builder: OfferBuilder, published: Published, wishes: FakeWishReader
) -> None:
    wishes.enabled_ids = {1}
    await _feed(pub_builder, _coupon_msg())
    [event] = published.events
    assert isinstance(event, CouponMatchedWish)
    assert [t.wish_id for t in event.targets] == [1]


async def test_no_targets_publishes_nothing(
    pub_builder: OfferBuilder, published: Published, wishes: FakeWishReader
) -> None:
    wishes.enabled_ids = set()
    await _feed(pub_builder, _coupon_msg())
    assert published.events == []


async def test_plain_product_publishes_nothing(
    pub_builder: OfferBuilder, published: Published
) -> None:
    await _feed(pub_builder, _product_msg(11))
    assert published.events == []


async def test_backfill_source_message_publishes_nothing(
    pub_builder: OfferBuilder, published: Published
) -> None:
    await _feed(pub_builder, _coupon_msg(source="backfill"))
    assert published.events == []


async def test_coupon_older_than_thirty_minutes_publishes_nothing(
    pub_builder: OfferBuilder, published: Published
) -> None:
    await _feed(pub_builder, replace(_coupon_msg(), date=NOW - timedelta(minutes=31)))
    assert published.events == []
    await _feed(pub_builder, replace(_coupon_msg(), date=NOW - timedelta(minutes=30)))
    assert len(published.events) == 1


async def test_ingest_many_and_rebuild_publish_nothing_even_for_fresh_live_messages(
    pub_builder: OfferBuilder, published: Published
) -> None:
    item = SourceMessage(_coupon_msg(), deleted=False, sold_out=False)
    assert pub_builder.ingest_many([item], source=MatchSource.retro) == 1
    assert pub_builder.ingest_many([item], source=MatchSource.live) == 1
    assert rebuild_offers(FakeMessageSource([item]), pub_builder) == 1
    await pub_builder.drain()
    assert published.events == []
    assert pub_builder._outbox == []


def test_builder_without_publish_never_grows_its_outbox(
    repo: InMemoryOfferRepository, wishes: FakeWishReader
) -> None:
    wishes.views = [_wish(1, 20000)]
    wishes.enabled_ids = {1}
    b = OfferBuilder(repo, wishes, FakeClock(NOW))
    b.ingest(_product_msg(10), source=MatchSource.retro)
    b.ingest(_coupon_msg())
    assert b._outbox == []


async def test_target_failure_is_logged_and_the_offer_stays_stored(
    pub_builder: OfferBuilder,
    published: Published,
    repo: InMemoryOfferRepository,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("db gone")

    monkeypatch.setattr(repo, "recent_store_offers", boom)
    with caplog.at_level(logging.ERROR):
        await _feed(pub_builder, _coupon_msg())
    assert repo.get(1, 50) is not None
    assert published.events == []
    assert [r for r in caplog.records if r.message == "coupon_targets_failed"]


async def test_publish_failure_is_logged_and_the_worker_keeps_running(
    pub_builder: OfferBuilder, published: Published, caplog: pytest.LogCaptureFixture
) -> None:
    published.fail = True
    with caplog.at_level(logging.ERROR):
        await _feed(pub_builder, _coupon_msg())
    assert [r for r in caplog.records if r.message == "coupon_event_publish_failed"]
    published.fail = False
    await _feed(pub_builder, replace(_coupon_msg(), message_id=51))
    assert len(published.events) == 1


async def test_retro_ingest_of_a_fresh_live_message_publishes_nothing(
    pub_builder: OfferBuilder, published: Published
) -> None:
    pub_builder.ingest(_coupon_msg(), source=MatchSource.retro)
    assert pub_builder._outbox == []
    await pub_builder.drain()
    assert published.events == []


async def test_failed_handle_discards_events_queued_before_the_failure(
    pub_builder: OfferBuilder, published: Published, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = pub_builder._queue_coupon_event

    def queue_then_fail(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("late failure")

    monkeypatch.setattr(pub_builder, "_queue_coupon_event", queue_then_fail)
    await _feed(pub_builder, _coupon_msg())
    assert pub_builder._outbox == []
    assert published.events == []


async def test_product_posted_23_hours_before_the_coupon_is_a_target(
    repo: InMemoryOfferRepository, wishes: FakeWishReader, published: Published
) -> None:
    wishes.views = [_wish(1, 20000)]
    wishes.enabled_ids = {1}
    b = OfferBuilder(repo, wishes, FakeClock(NOW), publish=published)
    old = replace(_product_msg(10), date=NOW - timedelta(minutes=5) - timedelta(hours=23))
    b.ingest(old, source=MatchSource.retro)
    await _feed(b, _coupon_msg())
    [event] = published.events
    assert isinstance(event, CouponMatchedWish)
    assert [t.wish_id for t in event.targets] == [1]


async def test_product_posted_two_and_a_half_days_before_the_coupon_is_not_a_target(
    repo: InMemoryOfferRepository, wishes: FakeWishReader, published: Published
) -> None:
    wishes.views = [_wish(1, 20000)]
    wishes.enabled_ids = {1}
    b = OfferBuilder(repo, wishes, FakeClock(NOW), publish=published)
    old = replace(_product_msg(10), date=NOW - timedelta(minutes=5) - timedelta(days=2, hours=12))
    b.ingest(old, source=MatchSource.retro)
    await _feed(b, _coupon_msg())
    assert published.events == []


async def test_target_gets_the_product_url(
    repo: InMemoryOfferRepository, pub_builder: OfferBuilder, published: Published
) -> None:
    repo.product_url_map["https://s.shopee.com.br/prod"] = "https://www.amazon.com.br/dp/B0C8814GKB"
    await _feed(pub_builder, _coupon_msg())
    [event] = published.events
    assert isinstance(event, CouponMatchedWish)
    assert [t.product_url for t in event.targets] == ["https://www.amazon.com.br/dp/B0C8814GKB"] * 2
    assert event.targets[0].offer_link == "https://s.shopee.com.br/prod"


async def test_product_url_lookup_failure_still_sends_the_event(
    repo: InMemoryOfferRepository,
    pub_builder: OfferBuilder,
    published: Published,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:

    def boom(links: object) -> dict[str, str]:
        raise RuntimeError("db")

    monkeypatch.setattr(repo, "product_urls", boom)
    with caplog.at_level(logging.WARNING):
        await _feed(pub_builder, _coupon_msg())
    [event] = published.events
    assert isinstance(event, CouponMatchedWish)
    assert [t.product_url for t in event.targets] == [None, None]
    [record] = [r for r in caplog.records if r.message == "product_link_lookup_failed"]
    assert record.__dict__["error"] == "RuntimeError"


async def test_partial_forward_origin_is_not_reported(
    pub_builder: OfferBuilder, published: Published
) -> None:
    await _feed(pub_builder, _coupon_msg(fwd_from_channel_id=77))
    [event] = published.events
    assert isinstance(event, CouponMatchedWish)
    assert (event.coupon_origin_channel_id, event.coupon_origin_message_id) == (None, None)


async def test_event_link_is_the_redeem_link(
    pub_builder: OfferBuilder, published: Published
) -> None:
    # The cart link comes first in `links`, so `main_link` differs from the redeem link.
    await _feed(pub_builder, replace(_coupon_msg(), links=COUPON_LINKS[::-1]))
    [event] = published.events
    assert isinstance(event, CouponMatchedWish)
    assert event.link == COUPON_LINKS[0]


def test_chatter_is_stored_but_never_matches_a_wish(
    repo: InMemoryOfferRepository, wishes: FakeWishReader
) -> None:
    wishes.views = [_wish(required=(("precin",),), max_price_cents=30000)]
    wishes.enabled_ids = {1}
    builder = OfferBuilder(repo, wishes, FakeClock(NOW))
    assert builder.ingest(_msg("Precin", links=(), has_photo=False))
    stored = repo.get(1, 2)
    assert stored is not None and stored.kind.value == "chatter"
    assert repo.priced_points(1) == []


def test_reclassifying_a_post_as_chatter_drops_the_matches_it_had(
    repo: InMemoryOfferRepository, wishes: FakeWishReader
) -> None:
    wishes.views = [_wish(required=(("precin",),), max_price_cents=30000)]
    wishes.enabled_ids = {1}
    builder = OfferBuilder(repo, wishes, FakeClock(NOW))
    # before the rule existed, the same post was a product and matched the wish
    repo.add_match(OfferMatch(1, 1, 2, None, NOW, MatchSource.live, NOW))
    assert len(repo.priced_points(1)) == 1
    builder.ingest(_msg("Precin", links=(), has_photo=False), source=MatchSource.retro)
    assert repo.priced_points(1) == []
