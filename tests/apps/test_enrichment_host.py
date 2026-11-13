import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.apps.enrichment import EnricherHost
from velkgram.offers.domain.links import FetchOutcome, FetchPlan
from velkgram.shared.config import Settings
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations


class _Fetcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(
        self,
        url: str,
        plan: FetchPlan,
        before_request: Callable[[str], None],
        budget_for: Callable[[str], int],
    ) -> FetchOutcome:
        self.calls.append(url)
        before_request(url)
        return FetchOutcome(url, (url,), 200, "text/html", None, "a.example")


class _Pages:
    def fetch(self, username: str) -> str | None:
        return None


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "v.db"
    conn = connect(db)
    apply_migrations(conn, MIGRATION_PACKAGES)
    conn.close()
    return db


def _add_offer(db: Path, message_id: int, link: str) -> None:
    conn = connect(db)
    posted = datetime(2026, 3, 1, tzinfo=UTC).isoformat()
    conn.execute(
        "INSERT INTO offers (channel_id, message_id, posted_at, title, has_photo, sold_out, "
        "deleted, updated_at, main_link) VALUES (1, ?, ?, 't', 0, 0, 0, ?, ?)",
        (message_id, posted, posted, link),
    )
    conn.commit()
    conn.close()


def _until(condition: Callable[[], bool], what: str, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, what
        time.sleep(0.01)


def _heartbeat_written(db: Path) -> bool:
    conn = connect(db)
    try:
        return conn.execute("SELECT 1 FROM link_enrich_state").fetchone() is not None
    finally:
        conn.close()


def _host(db: Path, fetcher: object, **kw: object) -> EnricherHost:
    return EnricherHost(
        Settings(db_path=db),
        make_fetcher=lambda: fetcher,  # type: ignore[arg-type,return-value]
        make_pages=lambda: _Pages(),  # type: ignore[arg-type,return-value]
        **kw,  # type: ignore[arg-type]
    )


def test_wake_makes_the_idle_enricher_follow_a_new_link_at_once(tmp_path: Path) -> None:
    db = _db(tmp_path)
    fetcher = _Fetcher()
    host = _host(db, fetcher)
    host.start()
    try:
        _until(lambda: _heartbeat_written(db), "the enricher never went idle")
        _add_offer(db, 1, "https://a.example/p")
        host.wake()
        _until(lambda: fetcher.calls == ["https://a.example/p"], "the wake-up was not acted on")
    finally:
        host.stop()


def test_stop_ends_every_worker_thread(tmp_path: Path) -> None:
    host = _host(_db(tmp_path), _Fetcher())
    host.start()
    host.stop()
    assert not [t for t in threading.enumerate() if t.name in ("link-enricher", "post-images")]


def test_a_crashed_enricher_is_logged_and_restarted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db = _db(tmp_path)
    _add_offer(db, 1, "https://a.example/p")
    fetcher = _Fetcher()
    attempts: list[int] = []

    def make_fetcher() -> _Fetcher:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("boom")
        return fetcher

    host = EnricherHost(
        Settings(db_path=db),
        make_fetcher=make_fetcher,  # type: ignore[arg-type]
        make_pages=lambda: _Pages(),  # type: ignore[arg-type,return-value]
        restart_delay_s=0.01,
    )
    with caplog.at_level(logging.ERROR):
        host.start()
        try:
            _until(lambda: bool(fetcher.calls), "the enricher did not come back after crashing")
        finally:
            host.stop()
    assert [r for r in caplog.records if r.message == "enricher_crashed"]
