"""The enricher's writes must never starve or fail the collector's offer upserts."""

import os
import sqlite3
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.offers.adapters.sqlite.links import SqliteLinkRepository
from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository, to_iso
from velkgram.offers.domain.models import Offer
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _offer(i: int, link: str) -> Offer:
    return Offer(
        channel_id=10,
        message_id=i,
        posted_at=T0 + timedelta(seconds=i),
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


def _bulk_offers(conn: sqlite3.Connection, n: int) -> None:
    conn.execute("BEGIN IMMEDIATE")
    conn.executemany(
        "INSERT INTO offers (channel_id, message_id, posted_at, title, has_photo, sold_out, "
        "deleted, updated_at, main_link) VALUES (1, ?, ?, 't', 0, 0, 0, ?, ?)",
        [(i, to_iso(T0), to_iso(T0), f"https://bulk.example/{i}") for i in range(n)],
    )
    conn.execute("COMMIT")
    # Else the first commit afterwards pays for checkpointing the whole bulk load.
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def test_upserts_and_link_saves_do_not_lock_each_other(tmp_path: Path) -> None:
    # Default run: correctness only (no lock errors, real overlap); wall-clock bounds
    # live in the slow variant so a busy machine can't flake the normal suite.
    _run_scenario(tmp_path, bulk=10_000, rounds=5, limit_s=None)


@pytest.mark.slow
def test_upserts_and_link_saves_do_not_lock_each_other_at_50k(tmp_path: Path) -> None:
    # A real lock fight shows up as errors or stalls near the 5 s busy_timeout, both still caught
    # here; a shared CI runner can add a one-off spike to the first write, so it gets more room.
    _run_scenario(tmp_path, bulk=50_000, rounds=20, limit_s=3.0 if os.environ.get("CI") else 0.5)


def _run_scenario(tmp_path: Path, *, bulk: int, rounds: int, limit_s: float | None) -> None:
    db = tmp_path / "c.db"
    setup = connect(db)
    apply_migrations(setup, MIGRATION_PACKAGES)
    seed = SqliteOfferRepository(setup)
    for i in range(200):
        seed.upsert(_offer(i, f"https://seed.example/{i}"))
    links = SqliteLinkRepository(setup)
    while links.discover(limit=50):
        pass
    rows = []
    while (row := links.next_due(T0 + timedelta(days=1), frozenset())) is not None:
        done = replace(row, status="done", store="amazon")
        links.save(done, fix_store=False)
        rows.append(done)
    assert len(rows) == 200
    _bulk_offers(setup, bulk)

    errors: list[BaseException] = []
    upsert_times: list[float] = []
    save_times: list[float] = []
    discover_phase = threading.Event()
    discover_phase_upserts: list[float] = []
    stop = threading.Event()

    def collector() -> None:
        conn = connect(db)
        repo = SqliteOfferRepository(conn)
        try:
            for i in range(200):
                t = time.perf_counter()
                repo.upsert(_offer(1000 + i, f"https://new.example/{i}"))
                upsert_times.append(time.perf_counter() - t)
            discover_phase.set()
            i = 0
            while not stop.is_set():
                t = time.perf_counter()
                repo.upsert(_offer(5000 + i, f"https://more.example/{i}"))
                discover_phase_upserts.append(time.perf_counter() - t)
                i += 1
        except BaseException as exc:
            errors.append(exc)
        finally:
            conn.close()

    def enricher() -> None:
        conn = connect(db)
        repo = SqliteLinkRepository(conn)
        try:
            for row in rows:
                t = time.perf_counter()
                repo.save(replace(row, title="T"), fix_store=True)
                save_times.append(time.perf_counter() - t)
            discover_phase.wait(timeout=30)
            for _ in range(rounds):
                assert repo.discover(limit=50) == 50
        except BaseException as exc:
            errors.append(exc)
        finally:
            stop.set()
            conn.close()

    threads = [threading.Thread(target=collector), threading.Thread(target=enricher)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=120)
    setup.close()

    assert errors == []
    assert len(save_times) == 200 and len(upsert_times) == 200
    assert discover_phase_upserts, "discover phase must overlap with upserts"
    if limit_s is not None:
        assert max(save_times) < limit_s
        assert max(upsert_times) < limit_s
        assert max(discover_phase_upserts) < limit_s
