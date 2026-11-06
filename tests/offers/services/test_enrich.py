import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.repositories import InMemoryLinkRepository, InMemoryOfferRepository
from velkgram.offers.domain.links import FetchOutcome, FetchPlan, Status
from velkgram.offers.domain.models import Offer
from velkgram.offers.domain.urls import host_of
from velkgram.offers.ports.fetcher import HostPaused
from velkgram.offers.services.enrich import LinkEnricher

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
KABUM = "https://www.kabum.com.br/produto/123456/ssd"
CUTT = "https://cutt.ly/abc"
TIDD = "https://tidd.ly/xyz"


def _offer(i: int, link: str | None, **kw: object) -> Offer:
    base = Offer(
        channel_id=10,
        message_id=i,
        posted_at=T0 + timedelta(minutes=i),
        title="SSD",
        price_cents=100,
        store=None,
        main_link=link,
        has_photo=False,
        text="t",
        norm_text="t",
        origin_channel_id=None,
        origin_message_id=None,
        sold_out=False,
        deleted=False,
        updated_at=T0,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


@dataclass
class Script:
    hops: tuple[str, ...]
    status: Status = 200
    body: str | None = None
    answered_by: str | None = None
    raises: Exception | None = None


@dataclass
class FakeFetcher:
    scripts: dict[str, Script] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def fetch(
        self,
        url: str,
        plan: FetchPlan,
        before_request: Callable[[str], None],
        budget_for: Callable[[str], int],
    ) -> FetchOutcome:
        self.calls.append(url)
        script = self.scripts.get(url, Script((url,), 200))
        if script.raises is not None:
            raise script.raises
        for hop in script.hops:
            try:
                before_request(hop)
            except HostPaused:
                return FetchOutcome(hop, script.hops, "paused", None, None, host_of(hop))
        final = script.hops[-1]
        return FetchOutcome(
            final, script.hops, script.status, "text/html", script.body,
            script.answered_by or host_of(final),
        )  # fmt: skip


class Env:
    def __init__(self) -> None:
        self.offers = InMemoryOfferRepository()
        self.links = InMemoryLinkRepository(self.offers)
        self.clock = FakeClock(T0 + timedelta(days=1))
        self.fetcher = FakeFetcher()
        self.waits: list[float] = []
        self.enricher = LinkEnricher(self.links, self.fetcher, self.clock, self._wait)

    def _wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        self.clock.advance(seconds)
        return False

    def add(self, i: int, link: str, **kw: object) -> None:
        self.offers.upsert(_offer(i, link, **kw))

    def row(self, url: str):
        return self.links._rows[url]


def _env_with(*links: str) -> Env:
    env = Env()
    for i, link in enumerate(links, start=1):
        env.add(i, link)
    return env


def test_newest_offer_is_enriched_first() -> None:
    env = _env_with("https://a.example/1", "https://b.example/2")
    assert env.enricher.step()
    assert env.fetcher.calls == ["https://b.example/2"]


def test_a_url_shared_by_many_offers_is_fetched_once() -> None:
    env = Env()
    for i in range(1, 4):
        env.add(i, "https://a.example/1")
    assert env.enricher.run(threading.Event(), until_idle=True) == 1
    assert env.fetcher.calls == ["https://a.example/1"]


def test_throttle_applies_on_intermediate_hops() -> None:
    env = _env_with(CUTT, TIDD)
    env.fetcher.scripts[CUTT] = Script((CUTT, TIDD, KABUM))
    env.fetcher.scripts[TIDD] = Script((TIDD, KABUM))
    env.enricher.step()  # TIDD offer is newest (message 2)
    env.enricher.step()
    # tidd.ly appears again, within 2 s of the previous request to it, so it waits
    assert any(0 < w <= 2.0 for w in env.waits)
    assert env.row(CUTT).status == "done"


def test_different_hosts_do_not_wait() -> None:
    env = _env_with("https://a.example/1", "https://b.example/2")
    env.enricher.step()
    env.enricher.step()
    assert env.waits == []


def test_403_from_final_host_pauses_that_host_but_others_proceed() -> None:
    env = _env_with("https://b.example/ok", "https://a.example/1", "https://a.example/2")
    env.fetcher.scripts["https://a.example/2"] = Script(("https://a.example/2",), 403)
    env.enricher.step()
    assert env.row("https://a.example/2").status == "blocked"
    assert env.row("https://a.example/2").blocks == 1
    assert env.row("https://a.example/2").attempts == 0
    assert env.enricher.step()  # a.example/1 is skipped (paused); b.example is processed
    assert env.fetcher.calls[-1] == "https://b.example/ok"
    assert not env.enricher.step()


def test_paused_host_gives_no_attempt() -> None:
    env = _env_with(CUTT)
    env.fetcher.scripts[CUTT] = Script((CUTT, KABUM), 403)
    env.enricher._paused["www.kabum.com.br"] = env.clock.now() + timedelta(minutes=5)
    env.enricher.step()
    row = env.row(CUTT)
    assert (row.status, row.attempts, row.blocks) == ("pending", 0, 0)


def test_magalu_403_with_id_in_url_is_done_and_does_not_pause() -> None:
    url = "https://www.magazineluiza.com.br/produto/p/123456789/"
    env = _env_with("https://www.magazineluiza.com.br/outro/", url)
    env.fetcher.scripts[url] = Script((url,), 403)
    env.enricher.step()
    row = env.row(url)
    assert (row.status, row.kind, row.product_id, row.store) == (
        "done",
        "product",
        "123456789",
        "magalu",
    )
    assert env.enricher._paused == {}


def test_error_retry_schedule_then_failed() -> None:
    env = _env_with("https://a.example/1")
    env.fetcher.scripts["https://a.example/1"] = Script(("https://a.example/1",), "error")
    expected = [timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=6)]
    for n, delay in enumerate(expected, start=1):
        assert env.enricher.step()
        row = env.row("https://a.example/1")
        assert row.attempts == n and row.status == "pending"
        assert row.next_try_at == env.clock.now() + delay
        assert not env.enricher.step()  # not due yet
        env.clock.advance(delay.total_seconds())
    assert env.enricher.step()
    row = env.row("https://a.example/1")
    assert (row.status, row.attempts) == ("failed", 4)


def test_5xx_counts_as_an_error() -> None:
    env = _env_with("https://a.example/1")
    env.fetcher.scripts["https://a.example/1"] = Script(("https://a.example/1",), 503)
    env.enricher.step()
    assert env.row("https://a.example/1").attempts == 1


def test_blocked_twice_gives_failed() -> None:
    env = _env_with("https://a.example/1")
    env.fetcher.scripts["https://a.example/1"] = Script(("https://a.example/1",), 429)
    env.enricher.step()
    row = env.row("https://a.example/1")
    assert row.status == "blocked" and row.next_try_at == env.clock.now() + timedelta(hours=24)
    env.clock.advance(24 * 3600)
    assert env.enricher.step()
    assert env.row("https://a.example/1").status == "failed"
    assert env.row("https://a.example/1").blocks == 2


def test_one_error_then_403_still_gets_its_block_retry() -> None:
    env = _env_with("https://a.example/1")
    url = "https://a.example/1"
    env.fetcher.scripts[url] = Script((url,), "error")
    env.enricher.step()
    env.clock.advance(300)
    env.fetcher.scripts[url] = Script((url,), 403)
    env.enricher.step()
    row = env.row(url)
    assert (row.status, row.attempts, row.blocks) == ("blocked", 1, 1)


@pytest.mark.parametrize("status", [404, 410, 301, 418, 200])
def test_terminal_statuses_are_done(status: int) -> None:
    env = _env_with("https://a.example/1")
    env.fetcher.scripts["https://a.example/1"] = Script(("https://a.example/1",), status)
    env.enricher.step()
    assert env.row("https://a.example/1").status == "done"


def test_invalid_is_done() -> None:
    env = _env_with("https://a.example/1")
    env.fetcher.scripts["https://a.example/1"] = Script(("https://a.example/1",), "invalid")
    env.enricher.step()
    assert env.row("https://a.example/1").status == "done"


def test_known_product_is_reused_without_fetch() -> None:
    first = "https://www.kabum.com.br/produto/123456/ssd"
    second = "https://www.kabum.com.br/produto/123456/ssd?tag=x"
    env = _env_with(first)
    env.fetcher.scripts[first] = Script(
        (first,),
        200,
        '<meta property="og:title" content="SSD 1TB"><meta property="og:image" content="https://img.example/a.jpg">',
    )
    env.enricher.step()
    env.add(2, second)
    env.clock.advance(61)
    env.enricher.step()
    assert env.fetcher.calls == [first]
    row = env.row(second)
    assert (row.status, row.title, row.image_url) == (
        "done",
        "SSD 1TB",
        "https://img.example/a.jpg",
    )
    assert "?" not in (row.final_url or "")


def test_store_fix_applies_only_to_offers_with_unknown_store() -> None:
    url = "https://www.kabum.com.br/produto/123456/ssd"
    env = Env()
    env.add(1, url)
    env.add(2, url, store="amazon")
    env.enricher.step()
    stores = {o.message_id: o.store for o in env.offers.all_offers()}
    assert stores == {1: "kabum", 2: "amazon"}


def test_exception_is_logged_without_url_and_counted(caplog: pytest.LogCaptureFixture) -> None:
    url = "https://a.example/1?tag=SECRET&ref=TOKEN"
    env = _env_with(url)
    env.fetcher.scripts[url] = Script((url,), raises=RuntimeError(f"boom {url}"))
    with caplog.at_level(logging.DEBUG):
        assert env.enricher.step()
    assert env.row(url).attempts == 1
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "SECRET" not in text and "TOKEN" not in text and "boom" not in text
    assert any(r.getMessage() == "link_enrich_failed" for r in caplog.records)
    assert all(r.exc_info is None for r in caplog.records)


def test_no_log_or_stored_url_carries_the_query_string(caplog: pytest.LogCaptureFixture) -> None:
    url = "https://a.example/1?tag=SECRET&ref=TOKEN"
    final = "https://b.example/p?tag=SECRET&ref=TOKEN"
    env = _env_with(url)
    env.fetcher.scripts[url] = Script((url, final), 200)
    with caplog.at_level(logging.DEBUG):
        env.enricher.step()
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "SECRET" not in text and "TOKEN" not in text
    final_url = env.row(url).final_url
    assert final_url == "https://b.example/p"


def test_discovery_is_bounded_when_batches_are_small() -> None:
    env = _env_with("https://a.example/1")
    calls: list[int] = []
    real = env.links.discover

    def counting(limit: int = 50) -> int:
        n = real(limit)
        calls.append(n)
        return n

    env.links.discover = counting  # type: ignore[method-assign]
    for _ in range(100):
        env.enricher.step()
        env.clock.advance(0.5)  # 50 s in total
    assert len(calls) == 1
    env.clock.advance(60)
    env.enricher.step()
    assert len(calls) == 2


def test_full_batches_discover_back_to_back_and_until_idle_drains_all() -> None:
    env = Env()
    for i in range(120):
        env.add(i, f"https://h{i}.example/p")
    calls: list[int] = []
    real = env.links.discover

    def counting(limit: int = 50) -> int:
        n = real(limit)
        calls.append(n)
        return n

    env.links.discover = counting  # type: ignore[method-assign]
    assert env.enricher.run(threading.Event(), until_idle=True) == 120
    assert calls[:3] == [50, 50, 20]


def test_run_limit_and_stop() -> None:
    env = Env()
    for i in range(5):
        env.add(i, f"https://h{i}.example/p")
    assert env.enricher.run(threading.Event(), limit=3) == 3
    stop = threading.Event()
    stop.set()
    assert env.enricher.run(stop) == 0


def test_idle_waits_until_next_try_capped_and_writes_heartbeat() -> None:
    env = _env_with("https://a.example/1")
    env.fetcher.scripts["https://a.example/1"] = Script(("https://a.example/1",), "error")
    stop = threading.Event()
    beats: list[datetime] = []
    real_beat = env.links.write_heartbeat
    env.links.write_heartbeat = lambda now: (beats.append(now), real_beat(now))[1]  # type: ignore[method-assign]

    def wait(seconds: float) -> bool:
        env.waits.append(seconds)
        env.clock.advance(seconds)
        if len(env.waits) >= 15:
            stop.set()
        return stop.is_set()

    enricher = LinkEnricher(env.links, env.fetcher, env.clock, wait)
    enricher.run(stop)
    assert max(env.waits) <= 10
    assert len(beats) >= 2  # after the URL, then once a minute while idle
    assert env.links.heartbeat() is not None
