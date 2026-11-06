# Telegram Bot Notifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Deliver every Velkgram alert to the owner's Telegram through a bot.

**Architecture:** A `TelegramBotNotifier` adapter in alerting implements the existing `Notifier` port. It runs on a second Telethon client in bot mode inside the collector process. A small alerting-owned `notifier_state` row feeds a line on the Status page. A `notify-test` CLI command checks the setup.

**Tech Stack:** Python 3.13, Telethon (already a dependency), SQLite, FastAPI and Jinja2, pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-velkgram-telegram-notifier-design.md`. Its values are binding.

## Global Constraints
- User-facing text is in pt-BR, with copy exactly as in spec §2. Everything else is in English.
- No new dependencies.
- `uv run lint-imports` keeps all 10 contracts:
  - the adapter lives in `velkgram/alerting/adapters/`;
  - only `velkgram/apps/` builds clients and wires adapters;
  - ingestion's status page gets plain data through an injected callable.
- Alert first:
  - the bot never blocks the collector's startup or ingestion;
  - a send failure raises `NotifierError`, and the existing retry and failed handling take over.
- The token never appears in logs, exception messages, the state detail or any rendered page. A test proves it.
- No test touches the network or a real Telegram client. Use fakes.
- TDD: run each test red before implementing. Full checks before each commit: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports && uv run pytest -q`.
- Never use `.env` or `data/velkgram.db` in tests. Never commit secrets. Never push.
- Load the skills `velkgram-architecture`, `velkgram-conventions`, `velkgram-testing` and `velkgram-task`.
- Subagents run on Sonnet or Haiku. Implementers never dispatch subagents and take no screenshots.

## Review Focus
1. **The owner never pressed Start, or blocked the bot.** Sends fail with a clear `needs_start` state, and nothing crashes. Covered in Task 1.
2. **Bad token or no network at startup.** Ingestion keeps running, alerts are `failed` and retried later, and the bot login is retried lazily. Covered in Task 2.
3. **Token leakage.** The token stays out of every log record, error message, state detail and the Status page. Covered in Tasks 1 and 2.
4. **A burst of alerts** (for example, coupon alerts for 10 wishes) is paced at 1 message per second without dropping any alert. Covered in Task 1.
5. **The chat goes to the right person.** Without `ALERT_CHAT_ID`, alerts go to the collector account's own id. With it set, they go to that chat. Covered in Task 2.

---

### Task 1: Config, notifier state and the bot adapter
Spec §2 (Config, Adapter, Notifier state), §4.

**Files:**
- Modify `velkgram/shared/config.py`.
- Create:
  - `velkgram/alerting/adapters/notify_telegram.py`;
  - `velkgram/alerting/migrations/003_notifier_state.sql`;
  - `velkgram/alerting/ports/notifier_state.py`;
  - `velkgram/alerting/adapters/sqlite/notifier_state.py`.
- Add the fake to `tests/fakes/`.
- Tests:
  - `tests/shared/test_config.py`;
  - `tests/alerting/adapters/test_notify_telegram.py`;
  - `tests/contracts/test_notifier_state.py`.

**Interfaces (produces):**
- **`Settings`** gains these fields:
  - `notifier: Literal["log", "telegram"]`;
  - `alert_bot_token: str | None = None`;
  - `alert_chat_id: int | None = None`.

  `load_settings` reads `NOTIFIER`, `ALERT_BOT_TOKEN` and `ALERT_CHAT_ID`. `telegram` without a token raises `ValueError("ALERT_BOT_TOKEN is required when NOTIFIER=telegram")`. `__repr__` masks the token with the existing `mask`.
- **`NotifierStatus`** is a `StrEnum`: `ok`, `needs_start`, `error`, `disabled`.
- **`NotifierStateStore` (Protocol)** has:
  - `set(status: NotifierStatus, detail: str | None, at: datetime) -> None`, which writes only when the status or the detail changed;
  - `get() -> tuple[NotifierStatus, str | None, datetime] | None`.

  It has an SQLite implementation and a fake. The migration creates `notifier_state(id INTEGER PRIMARY KEY CHECK (id = 1), status TEXT NOT NULL CHECK (status IN ('ok','needs_start','error','disabled')), detail TEXT, updated_at TEXT NOT NULL)`, with no BEGIN or COMMIT.
- **`BotClient` (Protocol, in the adapter module)** is the minimal surface of the Telethon client:
  - `async start(bot_token: str) -> None`;
  - `async send_message(entity: int, message: str, link_preview: bool) -> None`;
  - `async disconnect() -> None`.
- **`TelegramBotNotifier`** takes these arguments:

  ```python
  TelegramBotNotifier(
      client: BotClient,
      token: str,
      chat_id: Callable[[], int | None],
      state: NotifierStateStore,
      clock: Clock,
      monotonic: Callable[[], float] = time.monotonic,
      sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
  )
  ```

  - **`async ensure_started() -> bool`:** logs in at most once every 60 s, measured with `monotonic`. It writes `ok` or `error` to `state`, where the detail is the error class name only.
  - **`notify` and `notify_system`:** each call runs `ensure_started()` first; if that fails, it raises `NotifierError("bot_unavailable")`. It then takes the lock and waits until 1 s has passed since the last send. A missing chat id raises `NotifierError("no_chat")`.
  - **Text:** `notify` sends `format_alert(message)` with `link_preview=True`, and `notify_system` sends the raw text.
  - **Errors:** any exception from the client becomes `NotifierError(type(e).__name__)`. `UserIsBlockedError`, `PeerIdInvalidError` and `InputUserDeactivatedError` (matched by class name, so the domain stays free of Telethon) also set `needs_start`. A successful send sets `ok`.
  - **The token** goes only to `client.start`. It never appears in any message or log.

**Steps:**
- [ ] Write the failing config tests:
  - the default is `log`;
  - `telegram` without a token raises;
  - `telegram` with a token and a chat id parses;
  - a bad `ALERT_CHAT_ID` raises;
  - `repr` hides the token.
- [ ] Write the failing contract tests for `NotifierStateStore`, on both the fake and SQLite:
  - set and get;
  - a repeated set with the same values does not change `updated_at`.
- [ ] Write the failing adapter tests, using a fake `BotClient` that records calls and can be scripted to raise:
  - the text and the preview;
  - three quick sends sleep for 1 s and then 2 s;
  - each error becomes a `NotifierError`;
  - blocked or invalid peer sets `needs_start`;
  - after a failed login, the next send within 60 s doesn't retry the login, and the one after 60 s does;
  - no chat raises `no_chat`;
  - a log-capture test with a recognizable token string finds it in no record and in no exception text;
  - a burst of 10 sends delivers all 10, in order.
- [ ] Implement. Run the tests green, run the full checks, and commit `feat(alerting): telegram bot notifier, notifier state and config`.

### Task 2: Wiring, status line, notify-test and .env.example
Spec §2 (Client, Alert first, CLI, Compose, Status line), §4.

**Files:**
- Modify:
  - `velkgram/apps/collector/main.py`, to build the notifier from settings;
  - `velkgram/ingestion/adapters/telethon/client.py`, adding `build_bot_client(settings) -> TelegramClient` with an empty `StringSession` and `flood_sleep_threshold=0`;
  - `velkgram/apps/cli.py`, adding `cmd_notify_test`, registered in `COMMANDS` and the parser, with a module-level `_make_notifier(settings)` factory;
  - `velkgram/ingestion/web/router.py` and `status.html`, adding `notifier_status: Callable[[sqlite3.Connection], dict[str, object] | None] | None = None`;
  - `velkgram/apps/web/main.py`, wiring a helper that reads `NotifierStateStore.get()`;
  - `.env.example`, adding `NOTIFIER=log`, an empty `ALERT_BOT_TOKEN=`, an empty `ALERT_CHAT_ID=` and pt-BR comments.
- Tests:
  - `tests/apps/collector/` (wiring);
  - `tests/apps/test_cli_notify_test.py`;
  - `tests/ingestion/web/test_status_router.py`.

**Interfaces:**
- **Consumes** everything from Task 1.
- **Produces:**
  - **Collector startup:**
    - `NOTIFIER=log` keeps `LogNotifier` and sets the state to `disabled`.
    - `NOTIFIER=telegram` builds `TelegramBotNotifier(build_bot_client(settings), token, chat_id=…, state=SqliteNotifierStateStore(conn), …)`.
    - The chat id is `settings.alert_chat_id`. If that is unset, it is the user client's `(await client.get_me()).id`, read once after `is_user_authorized()`. Until then, the chat callable returns None.
    - `ensure_started()` runs as a background task, so it never blocks the collector's startup. The bot client is disconnected in `finally`.
  - **`velkgram notify-test`:**
    - loads settings and refuses with exit 2 when `NOTIFIER` is not `telegram`;
    - resolves the chat from `ALERT_CHAT_ID`, or from the user session's `get_me()`;
    - sends `Velkgram: teste de alerta ✅`;
    - prints `enviado` or `falhou: <ErrorClass>`, and exits 0 or 1;
    - applies migrations first.
  - **Status page lines:** exactly the strings in spec §2.

**Steps:**
- [ ] Write the failing wiring tests, with fake user and bot clients injected through `run(...)` parameters or factories:
  - alerts reach the fake bot end to end;
  - the chat is taken from `get_me` and from the override;
  - a bot whose `start` raises still lets ingestion store messages, the alert becomes `failed`, and the state is `error`;
  - `NOTIFIER=log` gives the `disabled` state.
- [ ] Write the failing CLI tests:
  - success;
  - failure;
  - `NOTIFIER=log` gives exit 2;
  - the token is not printed.
- [ ] Write the failing status page tests: all four lines, and no line when the callable isn't wired.
- [ ] Implement. Run the tests green, then run the full checks and `docker compose config -q`. Commit `feat(apps): wire telegram notifier, notify-test command and status line`.

## Execution
- Run Task 1, then Task 2. The two are reviewed together by one fresh, context-free reviewer, followed by a fix round if needed. Then one final whole-branch review.
- **Real check (controller):** with the owner's `.env`, run `velkgram notify-test` inside the collector container, then watch one real alert arrive. This requires the owner's OK, because it uses their real bot and session.
