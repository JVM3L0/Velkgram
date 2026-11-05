import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.repositories import FakeWishReader, InMemoryOfferRepository
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository, to_iso
from velkgram.offers.domain.build import wish_fingerprint
from velkgram.offers.domain.models import MatchSource, Offer, OfferMatch, RetroRun, RetroStatus
from velkgram.offers.services.retro_match import RetroMatcher
from velkgram.shared.db import connect
from velkgram.shared.deals import WishView
from velkgram.shared.events import WishlistChanged
from velkgram.shared.migrate import apply_migrations

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
CHANGED = WishlistChanged(version=1)


def _wish(wish_id: int = 1, term: str = "ssd", max_price: int = 30000) -> WishView:
    return WishView(
        id=wish_id, name=term, required=((term,),), excluded=(), max_price_cents=max_price
    )


def _offer(
    message_id: int,
    text: str = "ssd kingston por r$ 299,90",
    days_ago: int = 1,
    price: int | None = 29990,
) -> Offer:
    return Offer(
        channel_id=1,
        message_id=message_id,
        posted_at=NOW - timedelta(days=days_ago),
        title="t",
        price_cents=price,
        store=None,
        main_link=None,
        has_photo=False,
        text=text,
        norm_text=text,
        origin_channel_id=None,
        origin_message_id=None,
        sold_out=False,
        deleted=False,
        updated_at=NOW,
    )


class Env:
    def __init__(self) -> None:
        self.repo = InMemoryOfferRepository()
        self.wishes = FakeWishReader()
        self.sleeps: list[float] = []
        self.on_sleep = lambda: None
        self.matcher = RetroMatcher(
            self.repo,
            self.wishes,
            FakeClock(NOW),
            retention_days=90,
            sleep=self._sleep,
            chunk_size=500,
        )

    async def _sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.on_sleep()

    def matched_ids(self, wish_id: int = 1) -> set[int]:
        return {m.message_id for m in self.repo._matches.values() if m.wish_id == wish_id}


@pytest.fixture
def env() -> Env:
    return Env()


async def test_new_wish_gets_retro_matches_within_window(env: Env) -> None:
    env.repo.upsert(_offer(1, days_ago=10))
    env.repo.upsert(_offer(2, days_ago=100))
    env.wishes.views = [_wish()]
    await env.matcher.on_wishlist_changed(CHANGED)
    assert env.matched_ids() == {1}
    assert {m.source for m in env.repo._matches.values()} == {MatchSource.retro}
    run = env.repo.get_retro_run(1)
    assert run is not None
    assert run.status is RetroStatus.done
    assert run.finished_at == NOW
    assert run.fingerprint == wish_fingerprint(_wish())


async def test_retro_never_duplicates_live_match(env: Env) -> None:
    env.repo.upsert(_offer(1))
    env.repo.add_match(OfferMatch(1, 1, 1, 29990, NOW - timedelta(days=1), MatchSource.live, NOW))
    env.wishes.views = [_wish()]
    await env.matcher.on_wishlist_changed(CHANGED)
    assert len(env.repo._matches) == 1


async def test_unchanged_fingerprint_does_not_rerun(env: Env) -> None:
    env.repo.upsert(_offer(1))
    env.wishes.views = [_wish()]
    await env.matcher.on_wishlist_changed(CHANGED)
    env.repo.upsert(_offer(2))
    await env.matcher.on_wishlist_changed(CHANGED)
    assert env.matched_ids() == {1}


async def test_edit_recomputes_window_and_keeps_older_matches(env: Env) -> None:
    env.repo.upsert(_offer(1, days_ago=10))
    env.repo.upsert(_offer(2, days_ago=100))
    env.repo.add_match(OfferMatch(1, 1, 2, 29990, NOW - timedelta(days=100), MatchSource.live, NOW))
    env.wishes.views = [_wish()]
    await env.matcher.on_wishlist_changed(CHANGED)
    env.wishes.views = [_wish(max_price=40000)]
    await env.matcher.on_wishlist_changed(CHANGED)
    assert env.matched_ids() == {1, 2}
    run = env.repo.get_retro_run(1)
    assert run is not None
    assert run.fingerprint == wish_fingerprint(_wish(max_price=40000))


async def test_edit_during_run_restarts_with_new_fingerprint(env: Env) -> None:
    env.matcher = RetroMatcher(
        env.repo,
        env.wishes,
        FakeClock(NOW),
        retention_days=90,
        sleep=env._sleep,
        chunk_size=2,
    )
    for i in range(1, 7):
        env.repo.upsert(_offer(i, text="ssd kingston" if i % 2 else "teclado gamer", days_ago=i))
    env.wishes.views = [_wish(term="ssd")]
    edited = False

    def edit() -> None:
        nonlocal edited
        if not edited:
            edited = True
            env.wishes.views = [_wish(term="teclado")]

    env.on_sleep = edit
    await env.matcher.on_wishlist_changed(CHANGED)
    run = env.repo.get_retro_run(1)
    assert run is not None
    assert run.status is RetroStatus.running
    await env.matcher.on_wishlist_changed(CHANGED)
    run = env.repo.get_retro_run(1)
    assert run is not None
    assert run.status is RetroStatus.done
    assert run.fingerprint == wish_fingerprint(_wish(term="teclado"))
    assert env.matched_ids() == {2, 4, 6}


async def test_stale_running_run_is_resumed(env: Env) -> None:
    env.repo.upsert(_offer(1))
    env.wishes.views = [_wish()]
    env.repo.save_retro_run(
        RetroRun(1, wish_fingerprint(_wish()), RetroStatus.running, NOW, None, None)
    )
    await env.matcher.on_wishlist_changed(CHANGED)
    run = env.repo.get_retro_run(1)
    assert run is not None
    assert run.status is RetroStatus.done
    assert env.matched_ids() == {1}


async def test_failed_run_is_not_rerun_automatically(env: Env) -> None:
    env.repo.upsert(_offer(1))
    env.wishes.views = [_wish()]
    env.repo.save_retro_run(
        RetroRun(1, wish_fingerprint(_wish()), RetroStatus.failed, NOW, NOW, "OSError")
    )
    await env.matcher.on_wishlist_changed(CHANGED)
    run = env.repo.get_retro_run(1)
    assert run is not None
    assert run.status is RetroStatus.failed
    assert env.matched_ids() == set()


async def test_deleted_wish_data_is_removed(env: Env) -> None:
    env.repo.upsert(_offer(1))
    env.wishes.views = [_wish()]
    await env.matcher.on_wishlist_changed(CHANGED)
    env.wishes.views = []
    await env.matcher.on_wishlist_changed(CHANGED)
    assert env.repo.get_retro_run(1) is None
    assert env.matched_ids() == set()


async def test_yields_between_chunks() -> None:
    e = Env()
    matcher = RetroMatcher(
        e.repo, e.wishes, FakeClock(NOW), retention_days=90, sleep=e._sleep, chunk_size=2
    )
    for i in range(1, 6):
        e.repo.upsert(_offer(i, days_ago=i))
    e.wishes.views = [_wish()]
    await matcher.on_wishlist_changed(CHANGED)
    assert e.sleeps.count(0) >= 3


async def test_failure_marks_run_failed_and_is_not_raised(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    env.repo.upsert(_offer(1))
    env.wishes.views = [_wish()]

    def boom(_since: datetime, _size: int) -> object:
        raise OSError("disk")

    env.repo.iter_offers_with_text = boom  # type: ignore[method-assign,assignment]
    with caplog.at_level(logging.ERROR):
        await env.matcher.on_wishlist_changed(CHANGED)
    run = env.repo.get_retro_run(1)
    assert run is not None
    assert run.status is RetroStatus.failed
    assert run.error == "OSError"
    assert any("retro_match_failed" in r.getMessage() for r in caplog.records)


async def test_disabled_wish_is_matched_retroactively(env: Env) -> None:
    env.repo.upsert(_offer(1))
    env.wishes.views = [_wish()]
    env.wishes.enabled_ids = set()
    await env.matcher.on_wishlist_changed(CHANGED)
    assert env.matched_ids() == {1}


_POST = (
    "{kind} {n} - oferta imperdivel direto da loja oficial com frete gratis para todo o brasil, "
    "estoque limitado e cupom aplicado no carrinho. Corra antes que acabe, essa promocao costuma "
    "durar poucas horas e o preco historico nao deve se repetir tao cedo. Garantia de um ano "
    "do fabricante, nota fiscal e entrega rapida. Aproveite agora por r$ {price},90 no pix "
    "ou parcelado em ate 10x sem juros no cartao de credito de qualquer bandeira aceita."
)


@pytest.mark.slow
async def test_retro_180k_offers_under_10s(tmp_path: Path) -> None:
    factor = 5 if os.environ.get("CI") else 1
    conn = connect(tmp_path / "big.db")
    apply_migrations(conn, MIGRATION_PACKAGES)
    kinds = ["disco kingston", "teclado gamer", "monitor lg", "mouse sem fio", "cadeira office"]
    rows = []
    for i in range(180_000):
        kind = "notebook ssd" if i % 9 == 0 else kinds[i % 5]
        text = _POST.format(kind=kind, n=i, price=100 + i % 400)
        posted = to_iso(NOW - timedelta(minutes=i // 3))
        rows.append((1, i, posted, "t", (100 + i % 400) * 100, 0, text, text, 0, 0, posted))
    conn.execute("BEGIN")
    conn.executemany(
        "INSERT INTO offers (channel_id, message_id, posted_at, title, price_cents, has_photo,"
        " text, norm_text, sold_out, deleted, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.execute("COMMIT")
    repo = SqliteOfferRepository(conn)
    wishes = FakeWishReader()
    wishes.views = [_wish(term="ssd", max_price=10_000_000)]
    worst = 0.0
    last = time.perf_counter()

    async def sleep(_s: float) -> None:
        nonlocal worst, last
        now = time.perf_counter()
        worst = max(worst, now - last)
        last = time.perf_counter()

    matcher = RetroMatcher(repo, wishes, FakeClock(NOW), retention_days=3650, sleep=sleep)
    start = time.perf_counter()
    last = start
    await matcher.on_wishlist_changed(CHANGED)
    total = time.perf_counter() - start
    count = conn.execute("SELECT COUNT(*) FROM offer_matches WHERE wish_id = 1").fetchone()[0]
    print(f"retro 180k: total={total:.2f}s worst_chunk={worst * 1000:.1f}ms matches={count}")
    assert count == 20_000
    assert total < 10 * factor
    assert worst < 0.05 * factor
    conn.close()
