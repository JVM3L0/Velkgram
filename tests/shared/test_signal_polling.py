from pathlib import Path

from velkgram.shared.adapters.signal_polling import PollingChangeSignal
from velkgram.shared.db import bump_version, connect, transaction
from velkgram.shared.migrate import apply_migrations


async def test_signal_reports_only_changed_names(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, ["velkgram.shared"])
    signal = PollingChangeSignal(conn)
    assert await signal.changed() == {"wishlist": 0, "channels": 0}
    assert await signal.changed() == {}
    with transaction(conn):
        bump_version(conn, "channels")
    assert await signal.changed() == {"channels": 1}
    assert await signal.changed() == {}
