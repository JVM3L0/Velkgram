"""SQLite link repository. Every write is its own short transaction."""

import sqlite3
from datetime import UTC, datetime

from velkgram.offers.adapters.sqlite.repository import from_iso, to_iso
from velkgram.offers.domain.urls import host_of
from velkgram.offers.ports.links import EnrichHeartbeat, LinkRow
from velkgram.shared.db import transaction

_DUE = (
    "((status = 'pending' AND (next_try_at IS NULL OR next_try_at <= :now)) "
    "OR (status = 'blocked' AND next_try_at <= :now AND blocks < 2))"
)
_LIVE = "EXISTS (SELECT 1 FROM offers o WHERE o.main_link = product_links.url AND o.deleted = 0)"


def _opt_dt(value: str | None) -> datetime | None:
    return from_iso(value) if value is not None else None


def _to_row(r: sqlite3.Row) -> LinkRow:
    return LinkRow(
        id=int(r["id"]),
        url=r["url"],
        host=r["host"],
        offer_posted_at=from_iso(r["offer_posted_at"]),
        created_at=from_iso(r["created_at"]),
        final_url=r["final_url"],
        final_host=r["final_host"],
        store=r["store"],
        product_id=r["product_id"],
        title=r["title"],
        image_url=r["image_url"],
        kind=r["kind"],
        status=r["status"],
        attempts=int(r["attempts"]),
        blocks=int(r["blocks"]),
        next_try_at=_opt_dt(r["next_try_at"]),
        fetched_at=_opt_dt(r["fetched_at"]),
    )


def _not_paused(now: datetime, hosts: frozenset[str]) -> tuple[str, dict[str, str]]:
    """SQL fragment and named params: `now` plus one placeholder per paused host."""
    params = {"now": to_iso(now)}
    if not hosts:
        return "", params
    names = []
    for i, host in enumerate(sorted(hosts)):
        params[f"p{i}"] = host
        names.append(f":p{i}")
    marks = ", ".join(names)
    sql = f" AND host NOT IN ({marks}) AND (final_host IS NULL OR final_host NOT IN ({marks}))"
    return sql, params


class SqliteLinkRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def discover(self, limit: int = 50) -> int:
        # The scan runs outside any transaction (WAL readers never block the collector's writer);
        # only the small INSERT takes the write lock.
        found = self._conn.execute(
            "SELECT o.main_link AS url, MAX(o.posted_at) AS newest FROM offers o "
            "WHERE o.main_link IS NOT NULL AND o.deleted = 0 AND NOT EXISTS "
            "(SELECT 1 FROM product_links pl WHERE pl.url = o.main_link) "
            "GROUP BY o.main_link ORDER BY newest DESC LIMIT ?",
            (limit,),
        ).fetchall()
        if not found:
            return 0
        now = to_iso(datetime.now(UTC))
        with transaction(self._conn) as c:
            before = c.total_changes
            c.executemany(
                "INSERT OR IGNORE INTO product_links (url, host, offer_posted_at, created_at) "
                "VALUES (?, ?, ?, ?)",
                [(str(r["url"]), host_of(str(r["url"])), str(r["newest"]), now) for r in found],
            )
            return c.total_changes - before

    def next_due(self, now: datetime, paused_hosts: frozenset[str]) -> LinkRow | None:
        paused_sql, params = _not_paused(now, paused_hosts)
        row = self._conn.execute(
            f"SELECT * FROM product_links WHERE {_DUE} AND {_LIVE}{paused_sql} "
            "ORDER BY offer_posted_at DESC, id LIMIT 1",
            params,
        ).fetchone()
        return _to_row(row) if row is not None else None

    def earliest_next_try(self, now: datetime, paused_hosts: frozenset[str]) -> datetime | None:
        paused_sql, params = _not_paused(now, paused_hosts)
        row = self._conn.execute(
            "SELECT MIN(COALESCE(next_try_at, :now)) FROM product_links "
            "WHERE (status = 'pending' OR (status = 'blocked' AND blocks < 2)) "
            f"AND {_LIVE}{paused_sql}",
            params,
        ).fetchone()
        return _opt_dt(row[0])

    def known_product(self, store: str, product_id: str) -> tuple[str | None, str | None] | None:
        row = self._conn.execute(
            "SELECT title, image_url FROM product_links WHERE store = ? AND product_id = ? "
            "AND status = 'done' AND title IS NOT NULL ORDER BY id LIMIT 1",
            (store, product_id),
        ).fetchone()
        return (row["title"], row["image_url"]) if row is not None else None

    def save(self, row: LinkRow, *, fix_store: bool) -> int:
        final_host = host_of(row.final_url) if row.final_url else None
        with transaction(self._conn) as c:
            c.execute(
                "UPDATE product_links SET final_url = ?, final_host = ?, store = ?, "
                "product_id = ?, title = ?, image_url = ?, kind = ?, status = ?, attempts = ?, "
                "blocks = ?, next_try_at = ?, fetched_at = ? WHERE url = ?",
                (
                    row.final_url,
                    final_host,
                    row.store,
                    row.product_id,
                    row.title,
                    row.image_url,
                    row.kind,
                    row.status,
                    row.attempts,
                    row.blocks,
                    to_iso(row.next_try_at) if row.next_try_at else None,
                    to_iso(row.fetched_at) if row.fetched_at else None,
                    row.url,
                ),
            )
            if not (fix_store and row.store):
                return 0
            # updated_at stays put: the feed's "N novas" must not count a store fix as new.
            return c.execute(
                "UPDATE offers SET store = ? WHERE main_link = ? AND store IS NULL",
                (row.store, row.url),
            ).rowcount

    def write_heartbeat(self, now: datetime) -> None:
        with transaction(self._conn) as c:
            counts = {
                str(r[0]): int(r[1])
                for r in c.execute("SELECT status, COUNT(*) FROM product_links GROUP BY status")
            }
            c.execute(
                "INSERT INTO link_enrich_state (id, last_run_at, pending, done, failed, blocked) "
                "VALUES (1, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "last_run_at = excluded.last_run_at, pending = excluded.pending, "
                "done = excluded.done, failed = excluded.failed, blocked = excluded.blocked",
                (
                    to_iso(now),
                    counts.get("pending", 0),
                    counts.get("done", 0),
                    counts.get("failed", 0),
                    counts.get("blocked", 0),
                ),
            )

    def heartbeat(self) -> EnrichHeartbeat | None:
        row = self._conn.execute("SELECT * FROM link_enrich_state WHERE id = 1").fetchone()
        if row is None or row["last_run_at"] is None:
            return None
        return EnrichHeartbeat(
            from_iso(row["last_run_at"]),
            int(row["pending"]),
            int(row["done"]),
            int(row["failed"]),
            int(row["blocked"]),
        )
