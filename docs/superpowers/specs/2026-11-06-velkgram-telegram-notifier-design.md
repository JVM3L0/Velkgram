# Velkgram: Telegram bot notifier (design)

- **Status:** Approved in conversation on 2026-11-06. The owner created the bot and put `ALERT_BOT_TOKEN` in `.env`. Revised after plan review 1 (same day).
- **Builds on:** `2026-11-04-velkgram-design.md`: the `Notifier` port, the retries in NFR1 and §error handling, and "alert first".

## 1. Purpose
v1 shipped only `LogNotifier`, so no alert reaches the phone. A Telegram bot that the owner already started delivers every alert to the owner's own Telegram account. This covers v1 offer alerts, coupon alerts, retries and system messages.

## 2. Decisions
- **Config:**
  - `NOTIFIER=telegram` turns on the bot. `NOTIFIER=log` stays as it is today and stays the default.
  - With `telegram`, `ALERT_BOT_TOKEN` is required. A missing token is a config error in `load_settings`, so every service that loads settings fails fast on this misconfiguration (intended).
  - `ALERT_CHAT_ID` is optional (an int; a group id is allowed). When it is unset, the recipient is the collector's own account id, taken from `client.get_me()` on the user client after authorization.
  - `Settings.__repr__` masks the token. The chat id is not secret and is shown.
- **Client:**
  - A second Telethon `TelegramClient` with an empty `StringSession`, the same `TG_API_ID` and `TG_API_HASH`, and `start(bot_token=…)`. It runs in the collector process and event loop.
  - It is wrapped in a thin `TelethonBotClient` (ingestion Telethon adapter module) that matches the alerting `BotClient` protocol, so alerting never imports Telethon.
  - Each process start logs the bot in again. The bot session is not persisted.
  - Its `flood_sleep_threshold` is 0, so a FloodWait raises instead of sleeping inside the notifier.
  - A fresh bot session resolves a bare user id only after that user has messaged the bot. Before the owner presses Start, Telethon raises `ValueError` ("Could not find the input entity"); the server may also answer `PeerIdInvalidError` or `UserIsBlockedError`.
- **Adapter `TelegramBotNotifier`** (`velkgram/alerting/adapters/notify_telegram.py`), which implements `Notifier`:
  - `notify(message)` sends `format_alert(message)` as plain text with `link_preview=True`. `notify_system(text)` sends `text`.
  - Pacing: at most 1 message per second to the chat, through an `asyncio.Lock` plus a monotonic clock. Bursts queue behind the lock.
  - Its per-attempt budget is 10 s, not the default 1.5 s: `send_with_retry` honors an optional `attempt_timeout` attribute on the notifier. That leaves room for pacing and a lazy login.
  - `notify_system` bounds itself to 10 s and raises `NotifierError("timeout")`, so `Collector.fatal` never waits longer than that before writing its heartbeat.
  - Any Telethon or connection error, including `FloodWaitError`, is raised as `NotifierError` with the error class name only. The existing `send_with_retry` and `retry_failed` then do what they already do.
  - `UserIsBlockedError`, `PeerIdInvalidError` and `ValueError` (the owner never pressed Start, or blocked the bot) record the state `needs_start`. Every other failure records `error` with the class name.
  - Login is one shared background task: at most one login runs at a time, a cancelled waiter never cancels it, a login attempt is bounded to 8 s, and a new attempt starts at most once every 60 s.
- **Notifier state:** this is alerting-owned data.
  - A row `notifier_state(id = 1, status TEXT, detail TEXT, chat_id INTEGER, updated_at TEXT)`. The status is one of `ok`, `needs_start`, `error`, `disabled`.
  - The status is written on startup and after each send or login attempt, but only when the status or the detail changes.
  - `chat_id` stores the last chat resolved from `get_me()`. When the user session later dies (the case where a system alert matters most), the notifier falls back to it. Resolution order: `ALERT_CHAT_ID`, then this run's `get_me()`, then the stored id. On the very first run with a dead session and no `ALERT_CHAT_ID`, no chat is known and the system alert is only logged.
  - The Status page shows one line, read through an injected callable that takes a connection, the same pattern as the existing helpers:
    - "Bot de alertas: conectado"
    - "Bot de alertas: abra o bot no Telegram e toque em Iniciar"
    - "Bot de alertas: erro ({detail})"
    - "Bot de alertas: desativado (NOTIFIER=log)"
  - With no row yet, the page shows no line.
- **Alert first:**
  - If the bot can't log in (a bad token or no network), the collector still starts and ingests. `TelegramBotNotifier` raises `NotifierError` on every send until it connects, and it retries the login lazily, at most once a minute. Alerts become `failed` and are retried by the existing loop.
  - Bot startup never blocks the user client's startup.
  - The token never appears in logs, errors or the state detail.
- **CLI:** `velkgram notify-test` builds the same notifier and resolves the chat the same way. Without `ALERT_CHAT_ID`, it connects the user client (`TG_SESSION`), calls `get_me()` and disconnects, falling back to the stored chat id. It sends "Velkgram: teste de alerta ✅", prints "enviado" or "falhou: <ErrorClass>", and exits 0 or 1.
- **Compose:** no new service. The collector gets `NOTIFIER`, `ALERT_BOT_TOKEN` and `ALERT_CHAT_ID` from `.env` (already passed through `env_file`). Update `.env.example` with empty values and English comments.

## 3. Non-goals
- Bot commands (`/status`, muting).
- HTML or Markdown formatting.
- Per-wish routing.
- Persisting the bot session.

## 4. Testing
No network in any test. A fake Telethon-like client is injected.

- **Config:** `telegram` without a token is an error; the `ALERT_CHAT_ID` override; the masked repr.
- **Adapter:**
  - the text and the link preview;
  - 1 message per second (with a fake clock, 3 quick sends wait 1 s and 2 s);
  - each error class becomes a `NotifierError`, and the state is `needs_start` for blocked, invalid or unresolvable peers;
  - the token never appears in any log record or error message;
  - a lazy login retry: a failing login raises `NotifierError`, and the next send after 60 s tries the login again; concurrent sends share one login.
- **Retry service:** `send_with_retry` uses the notifier's `attempt_timeout` when present.
- **Collector wiring:** with `NOTIFIER=telegram` and a fake bot, an end-to-end alert arrives in the fake bot. A failing bot login doesn't prevent ingestion. The stored chat id is used when `get_me` is unavailable.
- **Status page:** the four lines, and no line without a row.
- **CLI:** `notify-test` succeeds and fails through a factory that the test monkeypatches.
- **Real check (controller):** `velkgram notify-test` with the owner's token, then one real alert.
