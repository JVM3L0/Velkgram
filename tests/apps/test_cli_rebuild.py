import sqlite3
from pathlib import Path

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.messages import NOW, msg
from velkgram.apps.cli import MIGRATION_PACKAGES, main
from velkgram.channels import ChannelCommands
from velkgram.channels.adapters.sqlite.repository import SqliteChannelRepository
from velkgram.ingestion.adapters.sqlite.repository import SqliteMessageRepository
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations
from velkgram.wishlist import WishCommands
from velkgram.wishlist.adapters.sqlite.repository import SqliteWishRepository

CH = -1001234567890


def test_rebuild_offers_command_builds_from_stored_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "v.db"
    conn = connect(db)
    apply_migrations(conn, MIGRATION_PACKAGES)
    clock = FakeClock(NOW)
    channel = ChannelCommands(SqliteChannelRepository(conn), clock).add("@loja")
    assert channel.id is not None
    conn.execute("UPDATE channels SET telegram_id=?, status='active' WHERE id=?", (CH, channel.id))
    conn.commit()
    messages = SqliteMessageRepository(conn, clock)
    messages.add(msg(1, CH, "Teclado mecanico R$ 200"))
    messages.add(msg(2, CH, "Mouse gamer R$ 100"))
    WishCommands(SqliteWishRepository(conn)).create("Teclado", ("teclado",), (), 50000)
    conn.close()

    monkeypatch.setenv("DB_PATH", str(db))
    assert main(["rebuild-offers"]) == 0
    assert capsys.readouterr().out.strip() == "rebuilt 2 offers"

    check = sqlite3.connect(db)
    assert check.execute("SELECT COUNT(*) FROM offers").fetchone()[0] == 2
    rows = check.execute("SELECT message_id, source FROM offer_matches").fetchall()
    check.close()
    assert rows == [(1, "retro")]
