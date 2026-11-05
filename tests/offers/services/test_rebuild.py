from dataclasses import replace
from datetime import UTC, datetime

from tests.fakes.clock import FakeClock
from tests.fakes.repositories import FakeMessageSource, FakeWishReader, InMemoryOfferRepository
from velkgram.offers import MatchSource, OfferBuilder, SourceMessage, rebuild_offers
from velkgram.shared.deals import WishView
from velkgram.shared.events import MessageData

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _msg(message_id: int = 1, text: str = "SSD Kingston 1TB por R$ 299,90") -> MessageData:
    return MessageData(
        1, message_id, NOW, NOW, text, ("https://amzn.to/x",), None, None, None, True, "backfill"
    )


class CountingWishReader(FakeWishReader):
    def __init__(self) -> None:
        super().__init__()
        self.all_calls = 0

    def all(self) -> list[WishView]:
        self.all_calls += 1
        return super().all()


class CountingRepo(InMemoryOfferRepository):
    def __init__(self) -> None:
        super().__init__()
        self.add_matches_calls = 0

    def add_matches(self, ms):  # type: ignore[no-untyped-def]
        self.add_matches_calls += 1
        return super().add_matches(ms)


def _wish(wish_id: int = 1) -> WishView:
    return WishView(
        id=wish_id, name="ssd", required=(("ssd",),), excluded=(), max_price_cents=30000
    )


def _setup(
    items: list[SourceMessage],
) -> tuple[FakeMessageSource, InMemoryOfferRepository, OfferBuilder]:
    repo = InMemoryOfferRepository()
    wishes = FakeWishReader()
    wishes.views = [_wish(1), _wish(2)]  # 2 is disabled: still gets matches (ruling 9)
    wishes.enabled_ids = {1}
    return FakeMessageSource(items), repo, OfferBuilder(repo, wishes, FakeClock(NOW))


def test_rebuild_builds_offers_and_retro_matches() -> None:
    source, repo, builder = _setup(
        [SourceMessage(_msg(1), False, False), SourceMessage(_msg(2), False, False)]
    )
    assert rebuild_offers(source, builder) == 2
    assert repo.get(1, 1) is not None and repo.get(1, 2) is not None
    assert len(repo._matches) == 4
    assert {m.source for m in repo._matches.values()} == {MatchSource.retro}


def test_rebuild_twice_changes_nothing() -> None:
    source, repo, builder = _setup([SourceMessage(_msg(1), False, False)])
    rebuild_offers(source, builder)
    offers, matches = dict(repo._offers), dict(repo._matches)
    assert rebuild_offers(source, builder) == 1
    assert repo._offers == offers
    assert repo._matches == matches


def test_rebuild_keeps_deleted_and_sold_out_flags() -> None:
    source, repo, builder = _setup(
        [SourceMessage(_msg(1), True, False), SourceMessage(_msg(2), False, True)]
    )
    rebuild_offers(source, builder)
    first, second = repo.get(1, 1), repo.get(1, 2)
    assert first is not None and first.deleted and not first.sold_out
    assert second is not None and second.sold_out and not second.deleted
    assert {m.message_id for m in repo._matches.values()} == {2}


def test_rebuild_does_not_clobber_purged_offers() -> None:
    source, repo, builder = _setup([SourceMessage(_msg(1), False, False)])
    rebuild_offers(source, builder)
    before = repo.get(1, 1)
    assert before is not None
    repo.upsert(replace(before, text=None, norm_text=None))
    purged_source = FakeMessageSource([SourceMessage(_msg(1, text=""), False, False)])
    rebuild_offers(purged_source, builder)
    after = repo.get(1, 1)
    assert after is not None
    assert after.title == before.title
    assert after.price_cents == 29990
    assert after.text is None and after.norm_text is None


def test_ingest_many_reads_wishes_once_and_batches_matches() -> None:
    repo = CountingRepo()
    wishes = CountingWishReader()
    wishes.views = [_wish(1)]
    builder = OfferBuilder(repo, wishes, FakeClock(NOW))
    items = [SourceMessage(_msg(i), False, False) for i in range(1, 6)]
    assert builder.ingest_many(items, source=MatchSource.retro) == 5
    assert wishes.all_calls == 1
    assert repo.add_matches_calls == 1
    assert len(repo._matches) == 5
    rebuild_offers(FakeMessageSource(items), builder, batch_size=2)
    assert wishes.all_calls == 1 + 3
    assert repo.add_matches_calls == 1 + 3


def test_ingest_many_handles_deleted_and_sold_out_items() -> None:
    repo = InMemoryOfferRepository()
    wishes = FakeWishReader()
    wishes.views = [_wish(1)]
    builder = OfferBuilder(repo, wishes, FakeClock(NOW))
    items = [
        SourceMessage(_msg(1), True, False),
        SourceMessage(_msg(2), False, True),
        SourceMessage(replace(_msg(3), text="", links=()), False, False),
    ]
    assert builder.ingest_many(items, source=MatchSource.retro) == 2
    assert repo.get(1, 1) is not None and repo.get(1, 1).deleted  # type: ignore[union-attr]
    assert repo.get(1, 2) is not None and repo.get(1, 2).sold_out  # type: ignore[union-attr]
    assert repo.get(1, 3) is None
    assert [m.message_id for m in repo._matches.values()] == [2]


def test_rebuild_fills_coupon_fields_on_existing_offers() -> None:
    text = "Cupom Shopee\n\nR$ 10 OFF em R$ 40: QIP98Q1ZXO\n\n-Resgate aqui:\nhttps://s.shopee.com.br/a"
    source, repo, builder = _setup([SourceMessage(_msg(1, text), False, False)])
    rebuild_offers(source, builder)
    offer = repo.get(1, 1)
    assert offer is not None
    assert offer.coupons == ("QIP98Q1ZXO",)
    assert offer.price_cents is None
    assert offer.redeem_link == "https://s.shopee.com.br/a"
