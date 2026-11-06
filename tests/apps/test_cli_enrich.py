import signal
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType

import pytest

from velkgram.apps import cli
from velkgram.apps.cli import MIGRATION_PACKAGES, main
from velkgram.offers.domain.links import FetchOutcome, FetchPlan
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations


class _Fetcher:
    def __init__(self, on_fetch: Callable[[], None] | None = None) -> None:
        self.calls: list[str] = []
        self._on_fetch = on_fetch

    def fetch(
        self,
        url: str,
        plan: FetchPlan,
        before_request: Callable[[str], None],
        budget_for: Callable[[str], int],
    ) -> FetchOutcome:
        self.calls.append(url)
        before_request(url)
        if self._on_fetch:
            self._on_fetch()
        return FetchOutcome(url, (url,), 200, "text/html", None, "a.example")


def _db(tmp_path: Path, n: int) -> Path:
    db = tmp_path / "v.db"
    conn = connect(db)
    apply_migrations(conn, MIGRATION_PACKAGES)
    now = datetime(2026, 3, 1, tzinfo=UTC)
    for i in range(n):
        posted = (now + timedelta(minutes=i)).isoformat()
        conn.execute(
            "INSERT INTO offers (channel_id, message_id, posted_at, title, has_photo, sold_out, "
            "deleted, updated_at, main_link) VALUES (1, ?, ?, 't', 0, 0, 0, ?, ?)",
            (i, posted, posted, f"https://h{i}.example/p"),
        )
    conn.commit()
    conn.close()
    return db


def _count(db: Path, status: str) -> int:
    c = sqlite3.connect(db)
    try:
        return c.execute("SELECT COUNT(*) FROM product_links WHERE status=?", (status,)).fetchone()[
            0
        ]
    finally:
        c.close()


def test_enrich_once_with_limit_processes_that_many(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path, 5)
    fetcher = _Fetcher()
    monkeypatch.setattr(cli, "_make_fetcher", lambda: fetcher)
    monkeypatch.setenv("DB_PATH", str(db))
    assert main(["enrich", "--once", "--limit", "2"]) == 0
    assert len(fetcher.calls) == 2
    assert _count(db, "done") == 2


def test_enrich_once_exits_when_idle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path, 3)
    monkeypatch.setattr(cli, "_make_fetcher", lambda: _Fetcher())
    monkeypatch.setenv("DB_PATH", str(db))
    assert main(["enrich", "--once"]) == 0
    assert _count(db, "done") == 3


def test_sigterm_handler_stops_the_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path, 5)
    previous = signal.getsignal(signal.SIGTERM)

    def send_sigterm() -> None:
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        frame: FrameType | None = None
        handler(signal.SIGTERM, frame)

    fetcher = _Fetcher(on_fetch=send_sigterm)
    monkeypatch.setattr(cli, "_make_fetcher", lambda: fetcher)
    monkeypatch.setenv("DB_PATH", str(db))
    try:
        assert main(["enrich"]) == 0  # no --once: only SIGTERM can end it
        assert len(fetcher.calls) == 1
    finally:
        signal.signal(signal.SIGTERM, previous)
