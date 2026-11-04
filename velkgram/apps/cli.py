"""Command-line entry point: `velkgram <command>`."""

import argparse
import asyncio
import getpass
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import replace

from telethon.sessions import StringSession

from velkgram.apps.web.auth import hash_password
from velkgram.ingestion.adapters.telethon.client import build_client
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


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "migrate": _migrate,
    "login": _login_cmd,
    "hash-password": _hash_password,
    "collector": _collector,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="velkgram")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply pending database migrations")
    sub.add_parser("login", help="interactive Telegram login; prints a StringSession")
    sub.add_parser("hash-password", help="hash a web password for WEB_PASSWORD_HASH")
    sub.add_parser("collector", help="run the Telegram collector")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)
