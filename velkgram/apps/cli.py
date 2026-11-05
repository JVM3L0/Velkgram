"""Command-line entry point: `velkgram <command>`."""

import argparse
import asyncio
import getpass
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime

from telethon.sessions import StringSession

from velkgram.alerting.adapters.sqlite.queries import SqliteAlertQueries
from velkgram.apps.web.auth import hash_password
from velkgram.ingestion.adapters.sqlite.queries import SqliteIngestionQueries
from velkgram.ingestion.adapters.telethon.client import build_client
from velkgram.reporting.adapters.alerting_api import AlertingAlertStats, price_extractor
from velkgram.reporting.adapters.ingestion_api import IngestionMessageStats
from velkgram.reporting.services.metrics import build_report
from velkgram.reporting.services.render import render_report
from velkgram.shared.config import load_settings
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

MIGRATION_PACKAGES = (
    "velkgram.shared",
    "velkgram.channels",
    "velkgram.wishlist",
    "velkgram.ingestion",
    "velkgram.alerting",
)


def _migrate(_args: argparse.Namespace) -> int:
    settings = load_settings(os.environ)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.db_path)
    try:
        applied = apply_migrations(conn, MIGRATION_PACKAGES)
    finally:
        conn.close()
    for name in applied:
        print(name)
    if not applied:
        print("no pending migrations")
    return 0


async def _login() -> None:
    settings = load_settings(os.environ)
    client = build_client(replace(settings, tg_session=None))
    try:
        await client.start()  # type: ignore[misc]
        print(StringSession.save(client.session))  # type: ignore[arg-type]
    finally:
        await client.disconnect()  # type: ignore[misc]


def _login_cmd(_args: argparse.Namespace) -> int:
    asyncio.run(_login())
    return 0


def _hash_password(_args: argparse.Namespace) -> int:
    first = getpass.getpass("Password: ")
    if not first:
        print("password must not be empty", file=sys.stderr)
        return 1
    if getpass.getpass("Repeat password: ") != first:
        print("passwords do not match", file=sys.stderr)
        return 1
    print(hash_password(first))
    return 0


def _collector(_args: argparse.Namespace) -> int:
    from velkgram.apps.collector.main import main as collector_main

    asyncio.run(collector_main())
    return 0


def _report(args: argparse.Namespace) -> int:
    since: date = args.since
    until: date = args.until or datetime.now(UTC).date()
    settings = load_settings(os.environ)
    conn = connect(settings.db_path)
    try:
        report = build_report(
            IngestionMessageStats(SqliteIngestionQueries(conn)),
            AlertingAlertStats(SqliteAlertQueries(conn)),
            price_extractor(),
            since,
            until,
            args.price_per_mtok,
        )
    finally:
        conn.close()
    print(render_report(report), end="")
    return 0


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date {value!r} (expected YYYY-MM-DD)") from None


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "migrate": _migrate,
    "login": _login_cmd,
    "hash-password": _hash_password,
    "collector": _collector,
    "report": _report,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="velkgram")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply pending database migrations")
    sub.add_parser("login", help="interactive Telegram login; prints a StringSession")
    sub.add_parser("hash-password", help="hash a web password for WEB_PASSWORD_HASH")
    sub.add_parser("collector", help="run the Telegram collector")
    report = sub.add_parser("report", help="usage report: volume, alerts, latency, token cost")
    report.add_argument("--since", type=_date, required=True, help="YYYY-MM-DD (UTC)")
    report.add_argument("--until", type=_date, default=None, help="YYYY-MM-DD (UTC), inclusive")
    report.add_argument("--price-per-mtok", type=float, default=None, help="USD per 1M tokens")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)
