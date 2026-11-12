import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from tests.offers.adapters._queries_helpers import T0, offer, put
from velkgram.apps.cli import MIGRATION_PACKAGES, main
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

AOC = 'Monitor Gamer Curvo Aoc Gaming U34g4c 34" Wqhd 180Hz'
TCL = "Monitor Gamer Tcl 25G64 25 Mini Led 300Hz"


def _db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    path = tmp_path / "p.db"
    monkeypatch.setenv("DB_PATH", str(path))
    conn = connect(path)
    apply_migrations(conn, MIGRATION_PACKAGES)
    now = T0 + timedelta(days=1)
    put(
        conn,
        offer(1, title=AOC, store="amazon", price=150000, at=now),
        offer(2, title=AOC, store="kabum", price=144400, at=now),
        offer(3, title=AOC, store="magalu", price=141900, at=now),
        offer(4, title=TCL, store="amazon", price=90000, at=now),
        offer(5, title=TCL, store="kabum", price=89600, at=now),
        offer(6, title="Camiseta Dry Fit Preta", store="amazon", price=5000, at=now),
        offer(
            7,
            title="Teclado Mecanico Redragon Kumara K552-RGB",
            store="amazon",
            price=18000,
            at=now,
        ),
    )
    return conn


def test_products_lists_each_product_with_stores_once_most_stores_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _db(tmp_path, monkeypatch)
    assert main(["products"]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("/produto/")]
    assert len(lines) == 2  # the AOC monitor once, the TCL once, the T-shirt not at all
    assert "3 lojas" in lines[0] and "U34g4c" in lines[0]  # most stores first
    assert "2 lojas" in lines[1] and "25G64" in lines[1]
    assert "R$ 1.419,00" in lines[0] and "R$ 1.500,00" in lines[0]  # the price range


def test_each_line_is_a_path_to_a_real_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _db(tmp_path, monkeypatch)
    main(["products"])
    path = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("/produto/"))
    channel, message = path.split()[0].removeprefix("/produto/").split("/")
    assert (int(channel), int(message)) == (1, int(message)) and int(message) in (1, 2, 3)


def test_products_can_print_full_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _db(tmp_path, monkeypatch)
    main(["products", "--base-url", "https://velkgram.example/"])
    assert "https://velkgram.example/produto/1/" in capsys.readouterr().out


def test_min_stores_one_also_lists_single_store_products(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _db(tmp_path, monkeypatch)
    main(["products", "--min-stores", "1"])
    out = capsys.readouterr().out
    assert "1 loja" in out and "K552-RGB" in out  # the single-store keyboard shows up
    assert "Camiseta" in out  # every priced product has a page now, code or not


def test_limit_caps_the_number_of_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _db(tmp_path, monkeypatch)
    main(["products", "--limit", "1"])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("/produto/")]
    assert len(lines) == 1


def test_groups_that_mostly_overlap_are_the_same_product() -> None:
    from velkgram.apps.cli import _overlapping

    a = frozenset((1, n) for n in range(1, 11))
    assert _overlapping(frozenset((1, n) for n in range(2, 12)), [a]) == 0  # 9 of 10 shared
    assert _overlapping(frozenset((1, n) for n in range(8, 20)), [a]) is None  # 3 of 10 shared
    assert _overlapping(a, []) is None
    assert _overlapping(frozenset({(1, 1)}), [frozenset({(1, 1), (1, 2)})]) == 0  # the smaller


def test_when_groups_overlap_the_fuller_one_is_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A smaller view seen first (newest card) must not hide the bigger view of the same product."""
    path = tmp_path / "o.db"
    monkeypatch.setenv("DB_PATH", str(path))
    conn = connect(path)
    apply_migrations(conn, MIGRATION_PACKAGES)
    put(
        conn,
        offer(1, title=AOC, store="amazon", price=150000, at=T0),
        offer(2, title=AOC, store="kabum", price=144400, at=T0 + timedelta(hours=1)),
        offer(3, title=AOC, store="magalu", price=141900, at=T0 + timedelta(hours=2)),
        offer(4, title=AOC, store="shopee", price=140000, at=T0 + timedelta(hours=3)),
    )
    assert main(["products", "--min-stores", "1"]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("/produto/")]
    assert len(lines) == 1 and "4 lojas" in lines[0]


def test_an_empty_database_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "empty.db"))
    assert main(["migrate"]) == 0
    capsys.readouterr()
    assert main(["products"]) == 0
    assert "nenhum produto" in capsys.readouterr().out.lower()
