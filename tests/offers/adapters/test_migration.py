import sqlite3
from collections.abc import Iterator
from importlib.resources import files
from pathlib import Path

import pytest

from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, MIGRATION_PACKAGES)
    yield c
    c.close()


def _insert(conn: sqlite3.Connection, text: str | None) -> None:
    conn.execute(
        "INSERT INTO offers (channel_id, message_id, posted_at, title, has_photo, text, "
        "sold_out, deleted, updated_at) VALUES (1, 1, '2026-01-01T00:00:00Z', 't', 0, ?, 0, 0, "
        "'2026-01-01T00:00:00Z')",
        (text,),
    )


def _hits(conn: sqlite3.Connection, term: str) -> int:
    return len(
        conn.execute("SELECT rowid FROM offers_fts WHERE offers_fts MATCH ?", (term,)).fetchall()
    )


def test_offers_tables_exist(conn: sqlite3.Connection) -> None:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"offers", "offers_fts", "offer_matches", "retro_runs"} <= names
    cols = {r[1] for r in conn.execute("PRAGMA table_info(retro_runs)")}
    assert "fingerprint" in cols


def test_fts_indexes_text_and_skips_null_text(conn: sqlite3.Connection) -> None:
    _insert(conn, "SSD Kingston 1TB")
    assert _hits(conn, "kingston") == 1
    conn.execute("UPDATE offers SET text = NULL")
    assert _hits(conn, "kingston") == 0


def test_fts_ignores_accents(conn: sqlite3.Connection) -> None:
    _insert(conn, "promoção")
    assert _hits(conn, "promocao") == 1


def test_comparable_column_defaults_to_true_and_backfills_coupon_titles(
    tmp_path: Path,
) -> None:
    c = connect(tmp_path / "old.db")
    c.executescript((files("velkgram.offers") / "migrations" / "001_offers.sql").read_text())
    for mid, title in ((1, "Cupom Kabum 10%"), (2, "SSD Kingston")):
        c.execute(
            "INSERT INTO offers (channel_id, message_id, posted_at, title, has_photo, sold_out, "
            "deleted, updated_at) VALUES (1, ?, '2026-01-01T00:00:00Z', ?, 0, 0, 0, "
            "'2026-01-01T00:00:00Z')",
            (mid, title),
        )
    migration = files("velkgram.offers") / "migrations" / "002_offer_comparable.sql"
    c.executescript(migration.read_text())
    rows = dict(c.execute("SELECT message_id, comparable FROM offers").fetchall())
    assert rows == {1: 0, 2: 1}
    c.close()


def test_coupon_migration_adds_columns_and_marks_coupon_titles(tmp_path: Path) -> None:
    c = connect(tmp_path / "old.db")
    for name in ("001_offers.sql", "002_offer_comparable.sql"):
        c.executescript((files("velkgram.offers") / "migrations" / name).read_text())
    for mid, title in ((1, "Cupom Shopee"), (2, "SSD Kingston")):
        c.execute(
            "INSERT INTO offers (channel_id, message_id, posted_at, title, price_cents, "
            "has_photo, sold_out, deleted, updated_at) VALUES (1, ?, '2026-01-01T00:00:00Z', ?, "
            "1000, 0, 0, 0, '2026-01-01T00:00:00Z')",
            (mid, title),
        )
    c.executescript((files("velkgram.offers") / "migrations" / "003_offer_coupons.sql").read_text())
    rows = c.execute(
        "SELECT message_id, kind, price_cents, coupons, coupon_discount, coupon_min_cents, "
        "coupon_scope, redeem_link, cart_link, coupon_tiers FROM offers ORDER BY message_id"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        (1, "coupon", None, None, None, None, None, None, None, None),
        (2, "product", 1000, None, None, None, None, None, None, None),
    ]


def test_migration_006_applies_on_a_populated_database(tmp_path: Path) -> None:
    c = connect(tmp_path / "pop.db")
    pass
    for name in sorted(
        p.name for p in (files("velkgram.offers") / "migrations").iterdir() if p.name < "006"
    ):
        if name.endswith(".sql"):
            c.executescript((files("velkgram.offers") / "migrations" / name).read_text())
    c.execute(
        "INSERT INTO offers (channel_id, message_id, posted_at, title, has_photo, sold_out, "
        "deleted, updated_at, main_link) VALUES (1, 1, '2026-01-01T00:00:00Z', 't', 0, 0, 0, "
        "'2026-01-01T00:00:00Z', 'https://a.example/1')"
    )
    c.executescript((files("velkgram.offers") / "migrations" / "006_product_links.sql").read_text())
    cols = {r[1] for r in c.execute("PRAGMA table_info(product_links)")}
    assert {"offer_posted_at", "host", "final_host", "blocks", "url", "status"} <= cols
    indexes = {r[1] for r in c.execute("PRAGMA index_list(offers)")}
    assert "idx_offers_main_link" in indexes
    assert c.execute("SELECT COUNT(*) FROM offers").fetchone()[0] == 1
    c.execute("INSERT INTO link_enrich_state (id) VALUES (1)")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO link_enrich_state (id) VALUES (2)")
    c.close()


def test_migration_007_creates_the_dominant_covering_indexes(tmp_path: Path) -> None:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, MIGRATION_PACKAGES)
    assert "idx_offers_key_cover" in {r[1] for r in c.execute("PRAGMA index_list(offers)")}
    cols = [r[2] for r in c.execute("PRAGMA index_info(idx_offer_matches_wish_cover)")]
    assert cols == ["wish_id", "channel_id", "message_id", "price_cents"]
    c.close()


def test_migration_008_drops_matches_of_coupon_posts(tmp_path: Path) -> None:
    c = connect(tmp_path / "pop.db")
    migrations = files("velkgram.offers") / "migrations"
    for name in sorted(p.name for p in migrations.iterdir() if p.name < "008"):
        if name.endswith(".sql"):
            c.executescript((migrations / name).read_text())
    for mid, kind in ((1, "product"), (2, "coupon")):
        c.execute(
            "INSERT INTO offers (channel_id, message_id, posted_at, title, has_photo, sold_out, "
            "deleted, updated_at, kind) VALUES (1, ?, '2026-01-01T00:00:00Z', 't', 0, 0, 0, "
            "'2026-01-01T00:00:00Z', ?)",
            (mid, kind),
        )
        c.execute(
            "INSERT INTO offer_matches (wish_id, channel_id, message_id, posted_at, source, "
            "matched_at) VALUES (1, 1, ?, '2026-01-01T00:00:00Z', 'live', '2026-01-01T00:00:00Z')",
            (mid,),
        )
    c.executescript((migrations / "008_drop_coupon_matches.sql").read_text())
    assert [r[0] for r in c.execute("SELECT message_id FROM offer_matches")] == [1]
    c.close()
