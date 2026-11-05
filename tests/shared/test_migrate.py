from pathlib import Path

from velkgram.shared.db import connect, read_versions
from velkgram.shared.migrate import apply_migrations


def test_apply_migrations_is_idempotent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    first = apply_migrations(conn, ["velkgram.shared"])
    assert first == ["velkgram.shared/001_state_versions.sql"]
    assert apply_migrations(conn, ["velkgram.shared"]) == []
    assert read_versions(conn) == {"wishlist": 0, "channels": 0}
