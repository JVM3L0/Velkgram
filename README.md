# Velkgram

Personal app that reads Telegram deal channels and alerts you in real time when an offer matches your wishlist: required/excluded keywords plus a maximum price.

> **Status: v0.2.0.** On top of v1 (collector, alert pipeline, web UI, usage report, Docker), it now builds an offers catalog with search, a feed, product pages with price history and a Material 3 UI with a light and a dark theme. Alerts go to the log only (WhatsApp is a separate spec). See [Status](#status).

- Design spec: [docs/superpowers/specs/2026-11-04-velkgram-design.md](docs/superpowers/specs/2026-11-04-velkgram-design.md)
- v0.2.0 design spec: [docs/superpowers/specs/2026-11-04-velkgram-v0.2.0-design.md](docs/superpowers/specs/2026-11-04-velkgram-v0.2.0-design.md)
- Implementation plans: [v1](docs/superpowers/plans/2026-11-04-velkgram-v1.md), [v0.2.0](docs/superpowers/plans/2026-11-04-velkgram-v0.2.0.md)

## How it works

```
Telegram channels ──push──▶ collector ──▶ store raw message (SQLite)
                                   └──▶ match wishlist → extract price → fast dedup
                                         └──▶ save alert → notify (background, 3 attempts)
                                   └──▶ build offer (title, price, store, link) → search index + match history
```

- **Reading:** a secondary Telegram *user* account over MTProto (Telethon). Events arrive by push, with no polling. Missed messages are recovered by backfill, which takes up to 200 messages or 6 h per channel.
- **Matching:** each wish has required terms, excluded terms and a max price in BRL. A term can list alternatives separated by `|`, e.g. `2tb|2 tb`. Matching ignores case and accents and respects word boundaries.
- **Price:** extracted from the post text with regexes (`R$ 1.299,90`, `de R$ 499 por R$ 349`, `por 589`). Installments (`10x R$ 119,90`) are ignored. If no price is found, the alert is still sent, flagged as "preço não identificado".
- **Dedup:** the same offer alerts only once within 30 min. That covers forwards of the same post, the same wish at the same price, and the same text when there is no price.
- **Offers:** every message becomes one offer: title, price, store (from the link domain) and main link, indexed with SQLite FTS5 for search. Every wish, enabled or not, gets an `offer_matches` history row for each matching offer; alerts are still sent only for enabled wishes. When you create or edit a wish, it is matched retroactively against the offers of the last `RETENTION_DAYS`.
- **Retention:** a daily job at 04:00 (`APP_TIMEZONE`) purges the message text older than `RETENTION_DAYS`. Offer summaries and match history are kept forever.
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
| `RETENTION_DAYS` | days to keep message text (default `90`, minimum `30`) |
| `APP_TIMEZONE` | IANA timezone for the daily purge and the web UI (default `America/Sao_Paulo`) |
| `WEB_PASSWORD_HASH`, `WEB_SECRET_KEY` | for the web UI. `WEB_PASSWORD_HASH` (from `uv run velkgram hash-password`) becomes the password of the `admin` account the first time the app starts; `WEB_SECRET_KEY` is any long random string |

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

Then start the collector (next section) and, once it is up, build the offers from the messages already stored:

```bash
uv run velkgram rebuild-offers   # only when upgrading or after a crash; idempotent
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

## Upgrading from v1

Order matters:

1. Pull the new code and run `uv run velkgram migrate`.
2. Start the new collector (stop the old v1 one first; never run two).
3. Run `uv run velkgram rebuild-offers`.

After a crash or hard stop, run `velkgram rebuild-offers` once: messages stored just before the stop may not have become offers yet.

Editing a wish recomputes its history only for the last `RETENTION_DAYS`; older matches are kept as they were, because their text has been purged.

An old collector running during the rebuild would ingest messages that never become offers. The rebuild is idempotent, so running it with the new collector up is safe. With Docker: `docker compose up -d --build`, then `docker compose run --rm collector velkgram rebuild-offers`.

## Web UI and report

```bash
uv run uvicorn --factory velkgram.apps.web.main:create_app --port 8000   # http://127.0.0.1:8000
uv run velkgram report                                                   # usage report
```

- **Feed (`/`):** the offers catalog with search, filters and infinite scroll. "Acompanhar" opens a new wish pre-filled from the offer.
- **Product page (`/wishes/{id}`):** stats, price chart (30 days, 90 days or all), matches and the retroactive status of the wish.
- **Wishes, channels, alerts, status and login** use Beer CSS 5.0.3 (Material 3 Expressive, self-hosted with a subset icon font). The theme menu offers system, dark and light (Gruvbox Material, "bem pastel" accents); the font is Bricolage Grotesque, self-hosted.

> The usage report only sees message text from the last `RETENTION_DAYS`, because older text is purged. Token-cost numbers for older dates undercount.

## Users

Several people can use one Velkgram. Channels, the collector and the offers are shared; each user has their own wishes, alerts and Telegram chat.

- **First login:** the user is `admin` and the password is the one behind `WEB_PASSWORD_HASH` (copied to the account at `velkgram migrate` and at web start, only while the account has no password). Your existing wishes belong to `admin`.
- **Create accounts** on the web (`/usuarios`, admin only: the password is generated and shown once) or from a shell:

  ```bash
  velkgram user add ana              # prompts for the password; add --admin for an administrator
  velkgram user passwd ana
  velkgram user disable ana          # also: enable, list, chat ana <telegram id>
  ```

- **Alerts go to each user's own chat.** Each person opens the bot in Telegram, taps **Iniciar**, and saves their numeric Telegram id on `/perfil` (get it from `@userinfobot`); the same page has a "send a test alert" button. A user with no chat gets a failed alert marked "Telegram não configurado" and nothing is sent to anyone else. `admin` keeps receiving alerts at `ALERT_CHAT_ID` (or the owner's own account) without setting an id.
- **Admin only:** channels, status and users. Regular users see the feed, coupons, their wishes and their alerts.
- A disabled user loses access on the next request and their wishes stop alerting. Someone else's wish answers 404.
- Alerts of a deleted wish disappear from the alerts page, since the page lists alerts by the user's current wishes.

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

## Railway

Railway volumes attach to a single service and the processes share one SQLite file, so everything runs in **one service**: `velkgram serve` migrates, then supervises the collector and the web UI (if one dies, both stop and Railway restarts the container). The link enricher runs as a thread of the collector: a live offer with a link publishes `OfferCreated` after the alert, which wakes the enricher at once. `velkgram enrich` remains for manual or `--once` runs; do not leave a long-running one next to a live collector, since two enrichers do not share the 2 s per-host request gap. `railway.toml` already sets the Dockerfile build, the start command, the `/login` healthcheck and the restart policy.

1. Push the repo to GitHub and create a Railway project from it (one service).
2. Add a **volume** to the service mounted at `/app/data`.
3. Set the variables below, then generate a public domain (Settings → Networking).
4. Check the logs for `no pending migrations` or the applied list, then open the domain and log in.

| Variable | Value |
|---|---|
| `DB_PATH` | `/app/data/velkgram.db` |
| `RAILWAY_RUN_UID` | `0` (the volume is root-owned; the image runs as uid 1000) |
| `TG_API_ID`, `TG_API_HASH`, `TG_SESSION` | from `velkgram login` |
| `NOTIFIER`, `ALERT_BOT_TOKEN`, `ALERT_CHAT_ID` | `telegram` plus the bot token and chat |
| `WEB_PASSWORD_HASH`, `WEB_SECRET_KEY` | from `velkgram hash-password` and a long random string |
| `WEB_HTTPS_ONLY` | `1` |

- Railway injects `PORT`; `serve` binds the web UI to it and trusts the proxy headers.
- Run only one replica. Two collectors on the same `TG_SESSION` break the session, and the volume is single-instance anyway. Stop the local container before the first deploy for the same reason.
- The UI is public on Railway, protected by the login (username and password, throttled per username) and the roles above. Use strong passwords. After the update, log in as `admin` with the password you already had.
- Copy the local `data/velkgram.db` into the volume only if you want to keep history (for example with `railway ssh`); otherwise it starts empty.
- Run one-off commands with `railway ssh` and `velkgram report --since YYYY-MM-DD`.

## Development

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports && uv run pytest -q
uv run ty check   # informational only
```

The architecture is a modular monolith with hexagonal modules (`channels`, `wishlist`, `ingestion`, `alerting`, `offers`, `reporting`, plus `shared` and `apps`). Module boundaries are enforced by `import-linter`, and the domain code is pure Python. The rules for contributors, human or agent, live in `.claude/skills/velkgram-*` and [CLAUDE.md](CLAUDE.md).

## Status

| Area | State |
|---|---|
| Storage (channels, wishes, messages, alerts) | ✅ done |
| Alert pipeline (matching, price, dedup, notify with retry) | ✅ done |
| Recovery (retry/expiry, restart without duplicates, reprocessing) | ✅ done |
| Telethon adapter, CLI (`migrate`, `login`, `hash-password`) | ✅ done |
| Collector runtime (`velkgram collector`) | ✅ done |
| Web UI (login, wishes, channels, alerts, status) | ✅ done |
| Multi-user (accounts, per-user wishes, alerts and Telegram chat, admin pages) | ✅ done |
| Offers (one per message, FTS5 search, match history, retention, `rebuild-offers`) | ✅ done |
| Offers feed (search, filters, infinite scroll, "Acompanhar") | ✅ done |
| Product page (stats, price chart, matches, retro status) | ✅ done |
| New UI (Beer CSS M3 Expressive, dark and light themes) | ✅ done |
| Usage report (`velkgram report`) | ✅ done |
| Docker / compose, healthcheck | ✅ done |
| Railway deploy (`velkgram serve`, `railway.toml`) | ✅ done |
| WhatsApp notifier | ⬜ separate spec, after v1 |
