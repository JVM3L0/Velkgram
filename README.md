# Velkgram

Personal app that reads Telegram deal channels and alerts you in real time when an offer matches your wishlist: required/excluded keywords plus a maximum price.

> **Status: v1 feature-complete (all 22 plan tasks implemented).** The collector, the alert pipeline, the web UI, the usage report and the Docker packaging are done. Alerts go to the log only (WhatsApp is a separate spec). See [Status](#status).

- Design spec: [docs/superpowers/specs/2026-11-04-velkgram-design.md](docs/superpowers/specs/2026-11-04-velkgram-design.md)
- Implementation plan: [docs/superpowers/plans/2026-11-04-velkgram-v1.md](docs/superpowers/plans/2026-11-04-velkgram-v1.md)

## How it works

```
Telegram channels ──push──▶ collector ──▶ store raw message (SQLite)
                                   └──▶ match wishlist → extract price → fast dedup
                                         └──▶ save alert → notify (background, 3 attempts)
```

- **Reading:** a secondary Telegram *user* account over MTProto (Telethon). Events arrive by push, with no polling. Missed messages are recovered by backfill, which takes up to 200 messages or 6 h per channel.
- **Matching:** each wish has required terms, excluded terms and a max price in BRL. A term can list alternatives separated by `|`, e.g. `2tb|2 tb`. Matching ignores case and accents and respects word boundaries.
- **Price:** extracted from the post text with regexes (`R$ 1.299,90`, `de R$ 499 por R$ 349`, `por 589`). Installments (`10x R$ 119,90`) are ignored. If no price is found, the alert is still sent, flagged as "preço não identificado".
- **Dedup:** the same offer alerts only once within 30 min. That covers forwards of the same post, the same wish at the same price, and the same text when there is no price.
- **Latency target:** under 10 s from the post to the notification, and under 200 ms inside the app.

## Requirements

- [uv](https://docs.astral.sh/uv/). It installs Python 3.13 for you.
- A Telegram account, preferably a secondary one, and an `api_id`/`api_hash` from <https://my.telegram.org>.
- Optional: Docker with Compose, to run everything with `docker compose up -d`.

## Setup

```bash
uv sync
cp .env.example .env
```

Edit `.env`. Empty values count as unset and fall back to the default.

| Variable | Value |
|---|---|
| `TG_API_ID`, `TG_API_HASH` | from my.telegram.org |
| `TG_SESSION` | output of `velkgram login` (see below) |
| `DB_PATH` | `./data/velkgram.db` |
| `NOTIFIER` | `log` (the only option in v1) |
| `LOG_LEVEL` | `INFO` |
| `WEB_PASSWORD_HASH`, `WEB_SECRET_KEY` | for the web UI. Generate the hash with `uv run velkgram hash-password`; `WEB_SECRET_KEY` is any long random string |

The app reads settings from environment variables only. Export them before running:

```bash
set -a; source .env; set +a
```

Wrap values that contain `$` or spaces in single quotes. The password hash is one of them (`WEB_PASSWORD_HASH='scrypt$…'`).

Create the session and the database:

```bash
uv run velkgram login      # needs TG_API_ID/TG_API_HASH exported; asks phone + code; prints a session string → put it in TG_SESSION
uv run velkgram migrate    # creates/updates the SQLite database
```

> ⚠️ `TG_SESSION` gives full access to the Telegram account. Never commit it, and never run the same session in two places at once, because Telegram may invalidate it.

## Running the collector

```bash
uv run velkgram collector
```

Manage channels and wishes in the web UI (below). Alternatively, add them directly in SQLite:

```bash
sqlite3 data/velkgram.db <<'SQL'
-- Channel by @username or invite hash (+AbC…); the collector resolves and joins it at startup.
INSERT INTO channels (ref, status, enabled, silent_after_hours, created_at)
VALUES ('@some_deal_channel', 'pending', 1, 12, strftime('%Y-%m-%dT%H:%M:%fZ','now'));

-- Wish: terms are JSON arrays (alternatives split by |; case and accents are ignored); price in cents.
INSERT INTO wishes (name, required_terms, excluded_terms, max_price_cents, enabled, created_at, updated_at)
VALUES ('SSD 2TB', '["ssd", "2tb|2 tb"]', '["usado"]', 60000, 1,
        strftime('%Y-%m-%dT%H:%M:%fZ','now'), strftime('%Y-%m-%dT%H:%M:%fZ','now'));
SQL
```

Changes made in the web UI reach the running collector automatically; after inserting rows by hand, restart it. When a matching offer arrives, stdout shows a JSON log line with `"event": "alert_notified"` and the alert in its `text` field.

## Web UI and report

```bash
uv run uvicorn --factory velkgram.apps.web.main:create_app --port 8000   # http://127.0.0.1:8000
uv run velkgram report                                                   # usage report
```

## Docker

`docker compose up -d` runs everything: a one-shot `migrate`, the `collector` (with a healthcheck and `restart: unless-stopped`) and the `web` UI.

```bash
cp .env.example .env     # fill TG_*, TG_SESSION, WEB_PASSWORD_HASH, WEB_SECRET_KEY
docker compose up -d --build
docker compose logs -f collector
docker compose run --rm migrate          # apply migrations by hand
docker compose run --rm collector velkgram report   # usage report
```

- The web UI is at <http://127.0.0.1:8000>. It is bound to localhost only. To reach it remotely, use a VPN such as Tailscale or a reverse proxy with TLS. Never expose it publicly.
- Data lives in `./data` (mounted at `/app/data`). Compose sets `DB_PATH=/app/data/velkgram.db` inside the containers, so the `DB_PATH` in your `.env` only matters for local runs.
- The collector healthcheck fails if the heartbeat is older than 90 s or the connection is in the `fatal` state.
- Run the collector in one place only: do not start `uv run velkgram collector` while the container is up (same session).

## Development

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports && uv run pytest -q
uv run ty check   # informational only
```

The architecture is a modular monolith with hexagonal modules (`channels`, `wishlist`, `ingestion`, `alerting`, `reporting`, plus `shared` and `apps`). Module boundaries are enforced by `import-linter`, and the domain code is pure Python. The rules for contributors, human or agent, live in `.claude/skills/velkgram-*` and [CLAUDE.md](CLAUDE.md).

## Status

| Area | State |
|---|---|
| Storage (channels, wishes, messages, alerts) | ✅ done |
| Alert pipeline (matching, price, dedup, notify with retry) | ✅ done |
| Recovery (retry/expiry, restart without duplicates, reprocessing) | ✅ done |
| Telethon adapter, CLI (`migrate`, `login`, `hash-password`) | ✅ done |
| Collector runtime (`velkgram collector`) | ✅ done |
| Web UI (login, wishes, channels, alerts, status) | ✅ done |
| Usage report (`velkgram report`) | ✅ done |
| Docker / compose, healthcheck | ✅ done |
| WhatsApp notifier | ⬜ separate spec, after v1 |
