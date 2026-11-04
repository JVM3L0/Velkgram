---
name: velkgram-conventions
description: Use when writing or reviewing any Velkgram code, SQL, log line, commit, or doc — naming and language rules (English code, Portuguese user-facing text), money/time/ID types, typing, async, error-handling ("alert first"), logging, and secrets.
---

# Velkgram conventions

## Language
- **Everything in the repo is English**: identifiers, modules, tables, columns, statuses, events, log messages, commits, docs, comments.
- **User-facing text is Portuguese (pt-BR)**: alert message bodies and web UI labels/templates. Keep it in templates/formatters, never in identifiers.

## Types and values
- **Money:** integer cents (`price_cents: int`), BRL. Never `float`. Format only at the edge (`R$ 1.299,90`).
- **Time:** timezone-aware UTC `datetime` in code, ISO-8601 strings in SQLite. Get "now" only through the `Clock` port. Never call `datetime.now()` in domain or services.
- **Telegram IDs:** numeric `int` (channels are `-100…`). Never use usernames as keys.
- **Domain models:** `@dataclass(frozen=True, slots=True)`. Event payloads likewise.
- **Statuses:** `enum.StrEnum` with lowercase values that match the spec (`pending`, `sent`, `failed`, `expired`).
- Full type hints everywhere. `pyright` strict in `*/domain` and `*/services`. No `Any` there.

## Code style
- `ruff` (lint + format) decides formatting. Don't hand-format.
- Python 3.13; `async`/`await` for I/O. Domain functions stay sync and pure.
- Small files with one purpose. If a file passes ~300 lines, split by responsibility.
- Comments explain **why**, not what. No commented-out code.
- Dependencies are injected by constructor. No module-level singletons except in `apps/*`.

## Errors: "alert first" (spec NFR2, §7)
- Nothing secondary may block or delay an alert. A raw-storage failure is logged; alerting continues.
- Catch errors **per message** in handlers: log with `channel_id`/`message_id` and keep going. Never let one bad message kill the listener.
- Never swallow silently: every `except` logs (structured) or re-raises. No bare `except:`.
- `FloodWaitError`: wait if ≤ 60 s, otherwise defer that operation. Never retry in a loop.
- Auth/session errors are **fatal**: notify once through `notify_system`, mark the heartbeat `fatal`, don't restart-loop.

## Logging
- Structured JSON to stdout via the stdlib `logging` + JSON formatter in `shared/`.
- Event-style messages: `logger.info("alert_sent", extra={"alert_id": ..., "latency_ms": ...})`.
- **Never log secrets**: session string, `api_hash`, password hash, provider tokens. Message text is fine at DEBUG.

## Secrets and config
- Only from env, through `shared/config.py`. Names in spec §9.
- Never commit `.env`, `*.session`, or DB files. `.gitignore` covers them. Check before every commit.
- One Telegram session per environment (spec §9).

## SQL
- Plain SQL in adapters, with parameters (`?`). Never string-format values into SQL.
- Migrations: `<module>/migrations/NNN_description.sql`, forward-only, idempotent DDL where possible.
- WAL + `busy_timeout=5000` are set in `shared/db.py`. Don't open connections elsewhere.

## Commits
- Conventional Commits: `feat(alerting): ...`, `fix(ingestion): ...`, `test(...)`, `refactor(...)`, `docs: ...`, `chore: ...`.
- One logical change per commit. Tests and code together.
- End with the `Co-Authored-By` trailer given by the session.
