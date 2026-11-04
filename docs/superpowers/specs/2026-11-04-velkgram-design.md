# Velkgram v1 — Design

- **Date:** 2026-11-04
- **Status:** Draft, awaiting review
- **Author:** João Victor Melo (with Claude)

## 1. Context

Velkgram is a personal app that reads Telegram deal channels and alerts its owner in real time when an offer matches their wishlist. Following ~30 deal channels by hand means reading thousands of repeated posts per day, and the good deals often sell out within minutes.

The core of the product is **real-time wishlist alerts**. A deduplicated feed, price history, and search set the long-term direction. They are out of scope for v1, but v1 stores raw data from day one so that they can be built later.

Black Friday (2026-11-27) is the expected volume peak. v1 should be collecting and alerting before it, so that peak traffic is measured with real data.

## 2. Goals and non-goals

### Goals (v1)
1. Alert on wishlist matches within **10 seconds** of the post reaching Telegram.
2. Never alert twice for the same offer within a 30-minute window.
3. Manage the wishlist and the monitored channels through a web UI, stored in the database.
4. Store every message, edit, and deletion raw, for reporting and future features.
5. Report volume, price-extraction coverage, duplicate rates, latency, and estimated LLM cost.
6. Keep the code modular, so that SQLite → Postgres, in-memory bus → Redis, and in-process → workers are adapter swaps, not rewrites.

### Non-goals (v1)
- Heavy deduplication: resolving short links, canonical store IDs, LLM extraction, embeddings, perceptual image hashing.
- Deduplicated feed, price history, search, daily digest.
- A real WhatsApp provider. v1 ships with `LogNotifier`, and the provider is chosen in its own spec.
- VPS deployment and CD pipeline (their own spec).
- Redis, Postgres, Temporal, multiple users.

## 3. Requirements

### Functional
- **FR1 — Sources.** Monitor up to ~30 Telegram **channels** (broadcast only; groups and supergroups are rejected) through a secondary **user account** over MTProto (Telethon). The user adds a channel by **`@username` or `t.me` link** (public or invite `t.me/+…`). After resolving it, the collector stores the numeric ID (`-100…`), and from then on all data is keyed by that ID, never by username.
- **FR2 — Wish items.** A wish has a name, **required terms**, **excluded terms**, a **max price** (BRL), and an enabled flag. A term may list alternatives separated by `|` (e.g. `2tb|2 tb|2000gb`).
- **FR3 — Matching.** A message matches a wish when every required term has at least one alternative present, no excluded alternative is present, and the extracted price is ≤ the max price.
- **FR4 — Unknown price.** If the terms match but no price can be extracted, alert anyway, flagged `price_unknown` ("⚠️ preço não identificado").
- **FR5 — Fast dedup.** Suppress an alert when any of these holds:
  (a) the message is a forward of a message that already produced an alert;
  (b) the same wish was alerted at the same price within 30 min;
  (c) with no price, the same wish was alerted for the same normalized-text hash within 30 min.
- **FR6 — Edits.** Store every edit as a new version. Re-evaluate the edit, and alert only if the message newly matches, has no previous alert, and was posted no more than 30 min ago (older offers are assumed gone). Flag `sold_out_hint` when the text contains sold-out phrases ("esgotado", "acabou", "encerrada"…). v1 sends no notification for it.
- **FR7 — Deletions.** Mark the message as deleted. Nothing is physically removed.
- **FR8 — Backfill.** On startup and on reconnect, fetch messages newer than `last_message_id` per channel (cap: 6 h or 200 messages). Backfilled messages younger than 30 min alert with `delayed_minutes`. Older ones are stored without alerting.
- **FR9 — Web UI.** Single-user login. CRUD for wishes and channels, alert history, a status page (connection, last message per channel, recent failures, silent channels). User-facing text is in Portuguese.
- **FR10 — Hot reload.** Wishlist and channel changes made in the web UI reach the collector within 5 s, without a restart. A newly added channel starts `pending`. The collector resolves the reference, joins the channel if needed (respecting `FloodWait`), and either marks it `active` with its numeric ID and title and runs a short backfill, or marks it `error` with a reason shown in the web UI (e.g. not a channel, invalid link, flood wait).
- **FR11 — Reporting.** A CLI report per day and per channel: message volume, price-extraction coverage, dedup rates by rule, alert counts, latency p50/p95, and estimated tokens plus LLM cost. The price per million tokens is a parameter, not a hardcoded value.
- **FR12 — Session bootstrap.** A CLI command logs in interactively and prints a Telethon `StringSession`.

### Non-functional
- **NFR1 — Latency.** Telegram→alert under 10 s end to end. The internal path (event in → `Notifier.notify` called) stays under 200 ms. Both are measured **at the moment the first `notify` call starts** (`latency_telegram_ms = now − date`, `latency_internal_ms = now − handler entry`, clamped at ≥ 0) and stored per alert. A slow or failing notifier must never delay the evaluation of later messages.
- **NFR2 — Alert first.** No secondary failure (raw storage, web, reporting) may block or delay an alert.
- **NFR3 — At-least-once processing.** Every stored message is evaluated at least once. Dedup makes reprocessing idempotent.
- **NFR4 — Account safety.** No bulk actions, `FloodWaitError` honored, sequential backfill with pauses, read-only behavior apart from joining configured channels.
- **NFR5 — Secrets.** The session string, `api_id`/`api_hash`, the web password hash, and provider credentials come only from the environment, are never committed, and are never logged.
- **NFR6 — Language.** Every project artifact (code, identifiers, tables, logs, commits, docs) is in English. Only user-facing text is in Portuguese.

## 4. Architecture

### 4.1 Style
A **modular monolith with hexagonal modules**:
- The system is split into business modules with strict boundaries (Spring Modulith / Shopify-style modular monolith).
- Each module is organized as ports and adapters on the inside (hexagonal, following *Architecture Patterns with Python* — "Cosmic Python").
- Modules talk to each other through **events** on an `EventBus` and through **public APIs** exposed in each module's `__init__.py`.

It runs as **two processes** in Docker Compose, sharing one SQLite database in WAL mode:
- `collector`: ingestion + alerting. This is the critical path and is rarely redeployed.
- `web`: FastAPI with server-rendered pages (Jinja2 + HTMX). Changes often. If it fails, the collector keeps alerting.

### 4.2 Layout

```
velkgram/
  shared/
    events.py            MessageReceived, MessageEdited, MessageDeleted,
                         AlertTriggered, WishlistChanged, ChannelsChanged
    ports.py             EventBus, Clock, ChangeSignal
    adapters/
      bus_memory.py      asyncio.Queue-based EventBus
      signal_polling.py  ChangeSignal over the state_versions table
      clock_system.py
    config.py            env parsing (typed settings)
    db.py                SQLite connection factory (WAL, busy_timeout)
  channels/
    domain/  ports/  services/  adapters/sqlite/  web/
  wishlist/
    domain/  ports/  services/  adapters/sqlite/  web/
  ingestion/
    domain/              Message, MessageVersion, normalization rules
    ports/               MessageRepository, TelegramGateway
    services/            ingest.py, backfill.py, gap_check.py
    adapters/telethon/   listener, gateway, Telethon → Message mapper
    adapters/sqlite/
  alerting/
    domain/              matching.py, pricing.py, dedup.py, models.py
    ports/               Notifier (notify(alert), notify_system(text)),
                         WishlistReader, AlertRepository
    services/            evaluate.py, notify.py, retry_failed.py, reprocess.py
    adapters/sqlite/
    adapters/notify_log.py
    web/                 alert history
  reporting/
    services/            metrics.py
    cli.py
  apps/
    collector/main.py    composition root: picks adapters from env
    web/main.py          composition root: mounts each module's web router
    cli.py               `velkgram login | report | migrate`
```

### 4.3 Dependency rules
These are enforced by `import-linter` contracts that run in CI.
1. `*/domain` imports nothing from the project except `shared.events` and `shared.text` (both pure), and no third-party I/O libraries.
2. `*/services` imports only its own `domain` and `ports`, plus `shared`.
3. Modules (`channels`, `wishlist`, `ingestion`, `alerting`, `reporting`) are **independent**: no module imports another module's internals. Cross-module access goes through events or a port whose adapter calls the other module's public API (e.g. `alerting.ports.WishlistReader` ← `wishlist` public API).
4. Only `apps/*` imports `*/adapters`. A module's public API (`__init__.py`) exports domain types, ports, and services, never adapter factories. Read queries are ports (`<module>/ports/queries.py`) implemented in `adapters/sqlite/queries.py` and wired by `apps`.
5. Each module owns its tables and migrations. No module reads another module's tables. Read access across modules goes through **query functions in the owner's public API** (e.g. `reporting` reads message and alert stats through `ingestion` and `alerting` public queries).
6. **Events carry plain data.** Payload dataclasses are defined in `shared/events.py` (ids, text, links, timestamps…), never in a module's domain types, so the consumer never imports the producer.
7. **Web pages live in the module that owns the data:** Wishes → `wishlist/web`, Channels → `channels/web`, Alerts → `alerting/web`, Status (heartbeat, per-channel last message, silent channels) → `ingestion/web`. Anything shown from another module comes through that module's public API.

### 4.4 Evolution path

| v1 | Later | Change needed |
|---|---|---|
| `bus_memory` | `bus_redis` (Streams + consumer groups) | new adapter; `ingestion` and `alerting` become separate workers |
| SQLite adapters | Postgres adapters | new adapters, passing the same contract tests |
| `signal_polling` | Redis pub/sub or bus events | new adapter |
| 2 compose services | N workers + redis + postgres | compose file + composition roots |
| — | `enrichment/` module (link resolution, LLM, embeddings), possibly on Temporal | new module consuming `AlertTriggered`/`MessageReceived` |

`domain` and `services` stay unchanged in every row.

## 5. Data model (SQLite)

All timestamps are UTC, stored as ISO-8601. Money is stored in integer cents.

**channels** (owned by `channels`)
| column | type | notes |
|---|---|---|
| id | INTEGER PK | internal row id |
| ref | TEXT UNIQUE | what the user typed, normalized (`@name` or `+hash`) |
| telegram_id | INTEGER UNIQUE NULL | Telegram channel ID (`-100…`), set on resolution |
| name | TEXT NULL | channel title, set on resolution |
| status | TEXT | `pending` / `active` / `error` |
| error | TEXT NULL | reason when `error` |
| enabled | INTEGER | 0/1 |
| silent_after_hours | INTEGER | default 12 |
| created_at | TEXT | |

The `channel_id` columns in other modules' tables hold `telegram_id`.

**wishes** (owned by `wishlist`)
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT | |
| required_terms | TEXT | JSON list; each item is `"a|b|c"` |
| excluded_terms | TEXT | JSON list |
| max_price_cents | INTEGER | |
| enabled | INTEGER | 0/1 |
| created_at, updated_at | TEXT | |

**messages** (owned by `ingestion`), PK (`channel_id`, `message_id`)
| column | type | notes |
|---|---|---|
| channel_id, message_id | INTEGER | |
| date | TEXT | Telegram timestamp |
| received_at | TEXT | when we got it |
| text | TEXT | raw text |
| links | TEXT | JSON list from entities + plain URLs |
| fwd_from_channel_id, fwd_from_message_id | INTEGER NULL | forward origin |
| grouped_id | INTEGER NULL | album |
| has_photo | INTEGER | 0/1; photos are not downloaded in v1 |
| source | TEXT | `live` / `backfill` |
| deleted_at | TEXT NULL | |
| processed_at | TEXT NULL | set by alerting after evaluation |

**message_versions** (owned by `ingestion`): `channel_id`, `message_id`, `version`, `edited_at`, `text`, `links`, `sold_out_hint`.

**ingestion_cursors** (owned by `ingestion`): `channel_id` PK, `last_message_id`, `updated_at`.

**alerts** (owned by `alerting`)
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| wish_id | INTEGER | |
| channel_id, message_id | INTEGER | triggering message |
| price_cents | INTEGER NULL | null when `price_unknown` |
| price_unknown | INTEGER | 0/1 |
| dedup_key | TEXT | see §6.3 |
| status | TEXT | `pending` / `sent` / `failed` / `expired` |
| attempts | INTEGER | |
| delayed_minutes | INTEGER NULL | set for backfilled messages |
| created_at, sent_at | TEXT | |
| latency_telegram_ms, latency_internal_ms | INTEGER | NFR1 |
| last_error | TEXT NULL | |

**alert_suppressions** (owned by `alerting`): `channel_id`, `message_id`, `wish_id`, `rule` (`origin` / `wish_price` / `wish_text`), `matched_alert_id`, `created_at`. Used to compute dedup rates.

**state_versions** (owned by `shared`): `name` PK (`wishlist`, `channels`), `version` INTEGER. Bumped by the web on every write.

**collector_heartbeat** (owned by `ingestion`): single row with `last_seen`, `connection_state` (`connected` / `reconnecting` / `fatal`), `fatal_reason`, and counters.

Migrations are plain SQL files per module, applied in order by `velkgram migrate`.

## 6. Data flow

### 6.1 Collector startup
1. Load enabled channels and wishes into memory, and record the `state_versions`.
2. Connect to Telegram with the `StringSession`.
3. Reprocess messages younger than 30 min with `processed_at IS NULL` (NFR3).
4. Backfill each channel sequentially from `ingestion_cursors` (FR8).
5. Start the live listener, the gap check (every 10 min), the change-signal poll (every 3 s), the failed-alert retry (every 1 min), and the heartbeat (every 30 s).

### 6.2 Critical path

```
Telegram ──push──▶ ingestion: NewMessage handler (no fixed chats filter)
  1. channel_id in in-memory enabled set? else drop
  2. map Telethon message → Message (text, entity links, fwd_from, grouped_id,
     has_photo, date, received_at)
  3. MessageRepository.add(message)              — failure is logged, not raised
  4. bus.publish(MessageReceived(message))
        ▼
alerting: MessageReceived consumer
  5. for each enabled wish in memory: terms match? (§6.3)
  6. price = extract_price(text); ≤ max_price, or price_unknown
  7. dedup check against the in-memory 30-min cache (§6.3); a suppression is recorded
  8. AlertRepository.add(status=pending) → Notifier.notify(alert)
  9. update status (sent/failed), latency fields; set processed_at;
     bus.publish(AlertTriggered)
```

Nothing on this path makes network calls apart from Telegram (inbound) and the notifier (outbound).

### 6.3 Domain rules
- **Text normalization** (shared by matching and dedup): lowercase, strip accents (`unicodedata` NFKD), drop emoji and URLs, collapse whitespace.
- **Term matching:** an alternative matches when it occurs in the normalized text on word boundaries. There is no implicit fuzziness: `2tb` doesn't match `2 tb` unless both are listed as alternatives.
- **One alert per (message, wish).** A message matching two wishes produces two alerts, each deduplicated on its own.
- **Price extraction**, in order:
  1. Collect `R$`-style values (`R$ 349`, `R$349,90`, `R$ 1.299,00`) and bare values right after `por`/`só`/`apenas`.
  2. Discard installment values (preceded by `\d+x de` or followed by `/mês`, `sem juros` patterns) and values explicitly marked as the old price (`de R$ X por`).
  3. If `de X por Y` is present, take Y. Otherwise take the first remaining value.
  4. If nothing remains, the price is `None`, which means `price_unknown`.
- **Dedup keys:**
  - origin: `org:{wish_id}:{channel_id}:{message_id}`, where the ids are the forward origin if the message is a forward and the message's own ids otherwise. An original post and every forward of it therefore share one key.
  - price: `wp:{wish_id}:{price_cents}`
  - text: `wt:{wish_id}:{sha1(normalized_text)}`
  - Window: 30 min. The cache lives in memory and is warmed from `alerts` at startup.

### 6.4 Edits and deletions
- `MessageEdited` → add a `message_versions` row, set `sold_out_hint`, publish `MessageEdited`. Alerting re-evaluates only if the message has no alert yet.
- `MessageDeleted` → set `deleted_at`.

### 6.5 Web changes
The web writes wishes or channels and bumps `state_versions` in the same transaction. The collector polls `state_versions` every 3 s, publishes `WishlistChanged`/`ChannelsChanged` on the bus, and its handlers reload whatever changed. For each `pending` channel it resolves and joins it (FR10), then runs a backfill. At startup the collector calls `get_dialogs()` once, to warm Telethon's entity cache for channels it already joined.

## 7. Error handling and resilience

| Failure | Behavior |
|---|---|
| Telegram disconnect | Telethon auto-reconnects (`catch_up=True`). A connection watcher checks `is_connected()` with every heartbeat (30 s): while disconnected, heartbeat `connection_state=reconnecting`; on recovery, backfill from cursors. |
| Silently missed updates | Gap check every 10 min: latest message per channel (`limit=1`) vs. cursor → backfill on mismatch. |
| `FloodWaitError` | Waits ≤ 60 s are handled automatically (`flood_sleep_threshold`). Longer waits are logged, only that operation is deferred, and nothing retries in a loop. |
| Auth failure (invalid, duplicated, or banned session) | Fatal: one `Notifier.notify_system` message, heartbeat `connection_state=fatal`, the process stays up idle (no restart loop), manual action required. |
| Per-message error | Caught per message, logged with ids; the listener continues. |
| Crash with queued events | Startup reprocessing of `processed_at IS NULL` < 30 min (NFR3). |
| Notifier failure | 3 attempts with backoff within ~8 s → `failed`. A background retry every 1 min handles `failed` < 30 min; older ones become `expired`. |
| SQLite busy/error | WAL + `busy_timeout=5000`. A failed raw-storage write never blocks alerting, and dedup keeps working from the in-memory cache. |
| Web down | No effect on the collector. |

**Observability:** structured JSON logs to stdout; a heartbeat row; a Docker healthcheck on heartbeat freshness; `restart: unless-stopped`, except that the fatal auth state doesn't restart. Channels silent for longer than `silent_after_hours` are flagged on the web status page.

## 8. Web UI

- **Login:** single user. The password hash (stdlib `hashlib.scrypt`) comes from `WEB_PASSWORD_HASH`, with a signed session cookie (`WEB_SECRET_KEY`). There is also a CLI helper that generates the hash.
- **Pages:** Wishes (list/create/edit/toggle/delete), Channels (list with status/add by `@username` or link/toggle/remove), Alerts (history with status, price, latency, link to the message), Status (heartbeat, per-channel last message, silent channels, recent failures).
- Server-rendered with Jinja2 + HTMX; no JS build. Each module contributes its own router under `<module>/web/`.

## 9. Configuration

| Env var | Used by | Notes |
|---|---|---|
| `TG_API_ID`, `TG_API_HASH` | collector, cli | secret |
| `TG_SESSION` | collector | secret, `StringSession`; never run the same session in two places at once |
| `DB_PATH` | all | default `./data/velkgram.db` |
| `NOTIFIER` | collector | `log` in v1 |
| `WEB_PASSWORD_HASH`, `WEB_SECRET_KEY` | web | secret |
| `LOG_LEVEL` | all | |

Docker Compose runs the services `collector` and `web`, both on the same image with different commands, sharing the `./data` volume.

## 10. Reporting

`velkgram report --since <date> [--until <date>] [--price-per-mtok <usd>]` prints, per day and per channel:
- message count; % of messages with an extracted price;
- alerts and suppressions by rule (`origin`, `wish_price`, `wish_text`);
- latency p50/p95 (`latency_telegram_ms`, `latency_internal_ms`);
- estimated tokens (`len(text) / 4`) and projected LLM cost for (a) all messages and (b) messages left after the fast dedup.

The per-day breakdown makes the Black Friday peak visible next to normal weeks.

## 11. Testing

| Layer | Scope | Approach |
|---|---|---|
| Domain | matching, pricing, dedup, normalization | table-driven tests with real Brazilian deal-post formats |
| Services | ingest → alerting → notify, backfill, reprocess, retry | in-memory fakes: repos, `FakeNotifier`, `FakeClock`, `MemoryBus` |
| Adapter contracts | each port implementation behaves identically | one shared suite per port, run against in-memory and SQLite (later Postgres/Redis) |
| Telethon adapter | Telethon → `Message` mapping | recorded message objects as fixtures; no live Telegram in CI; a manual smoke script for the real account |
| Web | routes, forms, auth | FastAPI `TestClient` + temp SQLite |
| Architecture | §4.3 rules | `import-linter` contracts |
| Latency | internal budget | inject `MessageReceived` → `FakeNotifier` called in < 200 ms |

After the collection period, a sample of real messages becomes regression fixtures for `pricing` and `matching`. Development follows TDD.

## 12. Tooling

- Python 3.13, **uv**, **ruff** (lint + format), **pytest** + **pytest-asyncio**, **import-linter**.
- **pyright** is the gating type checker (strict on `*/domain` and `*/services`).
- **ty** (Astral) runs in CI as **non-blocking**. Replace pyright with it once ty reaches a stable release and passes the strict modules cleanly.
- Runtime dependencies: `telethon`, `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `itsdangerous`.
- CI (GitHub Actions): `ruff check` → `ruff format --check` → `pyright` → `lint-imports` → `pytest`; `ty check` with `continue-on-error`.

## 13. Future direction (not in v1)

- **WhatsApp provider** (own spec): official WhatsApp Business Cloud API (template messages, per-message cost, dedicated number) vs. an unofficial gateway (Baileys/Evolution API; ban risk). Implemented as a `Notifier` adapter.
- **VPS + CD** (own spec): secrets in the CD secret store, one session per environment.
- **Heavy dedup / enrichment module:** short-link resolution with caching, canonical store IDs (ASIN, MLB…), EAN/GTIN lookup, LLM extraction to JSON, embeddings + exact checks on critical attributes. It is a candidate for Temporal-style durable workflows.
- **Deduplicated feed, price history, search, daily digest**, built from the stored raw data.
- **Channel ranking** (who posts first vs. who reposts), feedback (👍/👎) to tune thresholds, sold-out time stats from edits.

## 14. References

- Percival & Gregory, *Architecture Patterns with Python* (cosmicpython.com)
- Spring Modulith; Shopify's modular monolith / Packwerk
- Kamil Grzybek, *modular-monolith-with-ddd*
- Telethon documentation (events, `StringSession`, `iter_messages`, flood waits)
