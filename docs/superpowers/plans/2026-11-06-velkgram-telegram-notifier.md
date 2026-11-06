# Telegram Bot Notifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Deliver every Velkgram alert to the owner's Telegram through a bot.

**Architecture:** A `TelegramBotNotifier` adapter in alerting implements the existing `Notifier` port. It runs on a second Telethon client in bot mode inside the collector process, behind a small `BotClient` protocol so alerting never imports Telethon. A small alerting-owned `notifier_state` row feeds a line on the Status page and remembers the last chat id. A `notify-test` CLI command checks the setup.

**Tech Stack:** Python 3.13, Telethon 1.45 (already a dependency), SQLite, FastAPI and Jinja2, pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-velkgram-telegram-notifier-design.md`. Its values are binding.

## Global Constraints
- User-facing text is in pt-BR, with copy exactly as in spec §2. Everything else, including `.env.example` comments, is in English.
- No new dependencies.
- `uv run lint-imports` keeps all 10 contracts:
  - the notifier adapter lives in `velkgram/alerting/adapters/` and never imports Telethon or ingestion;
  - the Telethon bot wrapper lives in `velkgram/ingestion/adapters/telethon/client.py` and never imports alerting (it satisfies `BotClient` structurally);
  - only `velkgram/apps/` builds clients and wires adapters;
  - ingestion's status page gets plain data through an injected callable.
- Alert first:
  - the bot never blocks the collector's startup or ingestion;
  - a send failure raises `NotifierError`, and the existing retry and failed handling take over.
- The token never appears in logs, exception messages, the state detail or any rendered page. Tests prove it. Login failures are logged with `log.warning(..., extra={"error": type(e).__name__})`, never `log.exception` and never `str(e)`.
- No test touches the network or a real Telegram client. Use fakes. Whenever a test injects a fake `sleep`, that fake sleep advances the fake `monotonic` by the slept amount.
- TDD: run each test red before implementing. Full checks before each commit: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports && uv run pytest -q`.
- Never use `.env` or `data/velkgram.db` in tests. Never commit secrets. Never push.
- Load the skills `velkgram-architecture`, `velkgram-conventions`, `velkgram-testing` and `velkgram-task`.
- Subagents run on Sonnet or Haiku. Implementers never dispatch subagents and take no screenshots.

## Review Focus
1. **The owner never pressed Start, or blocked the bot.** Telethon raises `ValueError` (unresolvable peer), `PeerIdInvalidError` or `UserIsBlockedError`; all three give `needs_start`, and nothing crashes. Task 1.
2. **Bad token or no network at startup.** Ingestion keeps running, alerts are `failed` and retried later, the bot login is retried lazily, and concurrent sends never start two logins. Tasks 1 and 2.
3. **Timeouts.** Pacing plus login fit inside the notifier's 10 s attempt budget, which `send_with_retry` honors; `notify_system` is bounded to 10 s so `fatal()` still writes its heartbeat. Task 1.
4. **Token leakage.** The token stays out of every log record, error message, state detail and the Status page, including when the fake login raises an exception whose text contains the token. Tasks 1 and 2.
5. **The chat goes to the right person, even when the user session is dead.** Order: `ALERT_CHAT_ID`, this run's `get_me()`, the stored chat id. Task 2.

---

### Task 1: Config, notifier state, retry budget and the bot adapter
Spec §2 (Config, Adapter, Notifier state), §4.

**Files:**
- Modify:
  - `velkgram/shared/config.py`;
  - `velkgram/alerting/services/notify.py` (honor `attempt_timeout`).
- Create:
  - `velkgram/alerting/adapters/notify_telegram.py`;
  - `velkgram/alerting/migrations/003_notifier_state.sql` (`003` is the next free number; `velkgram.alerting` is already in `MIGRATION_PACKAGES`);
  - `velkgram/alerting/ports/notifier_state.py`;
  - `velkgram/alerting/adapters/sqlite/notifier_state.py`.
- Add the `NotifierStateStore` fake and a `FakeBotClient` to `tests/fakes/`.
- Tests:
  - `tests/shared/test_config.py`;
  - `tests/alerting/services/test_notify.py` (or the existing `send_with_retry` test file, if one exists);
  - `tests/alerting/adapters/test_notify_telegram.py`;
  - `tests/contracts/test_notifier_state.py`.

**Interfaces (produces):**
- **`Settings`** gains these fields:
  - `notifier: Literal["log", "telegram"]`;
  - `alert_bot_token: str | None = None`;
  - `alert_chat_id: int | None = None`.

  `load_settings` reads `NOTIFIER`, `ALERT_BOT_TOKEN` and `ALERT_CHAT_ID`. The existing `unknown NOTIFIER` guard becomes a membership test over `("log", "telegram")`. `telegram` without a token raises `ValueError("ALERT_BOT_TOKEN is required when NOTIFIER=telegram")`. A non-integer `ALERT_CHAT_ID` raises `ValueError`. The hand-written `__repr__` masks the token with the existing `mask` and shows `alert_chat_id` as is.
- **`send_with_retry`** keeps its signature. Each attempt uses `getattr(notifier, "attempt_timeout", attempt_timeout)` as its timeout, and the timeout error text uses that value.
- **`NotifierStatus`** is a `StrEnum`: `ok`, `needs_start`, `error`, `disabled`.
- **`NotifierStateStore` (Protocol)** has:
  - `set(status: NotifierStatus, detail: str | None, at: datetime) -> None`, which writes only when the status or the detail changed;
  - `get() -> tuple[NotifierStatus, str | None, datetime] | None`;
  - `set_chat_id(chat_id: int) -> None` and `get_chat_id() -> int | None`.

  `set_chat_id` updates only the `chat_id` column. On a missing row it is a no-op, so callers always `set` a status first (the collector and `notify-test` do: the login or send records one before any `set_chat_id` matters, and the collector records `disabled`/login state at startup). `get_chat_id` returns `None` without a row.

  It has an SQLite implementation and a fake. The migration creates `notifier_state(id INTEGER PRIMARY KEY CHECK (id = 1), status TEXT NOT NULL CHECK (status IN ('ok','needs_start','error','disabled')), detail TEXT, chat_id INTEGER, updated_at TEXT NOT NULL)`, with no BEGIN or COMMIT. `set` never clears `chat_id`.
- **`BotClient` (Protocol, in the adapter module):**
  - `async start(bot_token: str) -> None`;
  - `async send_message(chat_id: int, text: str, *, link_preview: bool) -> None`;
  - `async disconnect() -> None`.
- **`TelegramBotNotifier`:**

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

  Class constants: `attempt_timeout = 10.0`, `LOGIN_TIMEOUT_S = 8.0`, `LOGIN_RETRY_S = 60.0`, `SYSTEM_TIMEOUT_S = 10.0`, `MIN_INTERVAL_S = 1.0`.

  - **`begin_login() -> None`:** starts the shared login task if none is running, the bot is not started, and no attempt started in the last `LOGIN_RETRY_S` (measured with `monotonic`, from the start of the previous attempt). Never awaits. The collector calls it once at startup.
  - **`async ensure_started() -> bool`:** returns `True` when started. Otherwise it calls `begin_login()` and, if a login task exists, awaits it through `asyncio.shield` so a cancelled caller never cancels the login. Returns `False` when throttled or when the login failed. Idempotent and concurrency-safe: N concurrent callers cause one `client.start` call.
  - **The login task** runs `client.start(token)` inside `asyncio.timeout(LOGIN_TIMEOUT_S)`. On success it records `ok`. On any exception it records `error` with the class name only (`TimeoutError` on timeout), logs `bot_login_failed` with the class name, and calls `client.disconnect()` inside `contextlib.suppress(Exception)`.
  - **`notify` and `notify_system`:** `ensure_started()` first; if it returns `False`, raise `NotifierError("bot_unavailable")`. A missing chat id raises `NotifierError("no_chat")`. Then take the lock, wait with `sleep` until `MIN_INTERVAL_S` has passed since the previous send started, and send. `notify_system` wraps all of this in `asyncio.timeout(SYSTEM_TIMEOUT_S)` and turns `TimeoutError` into `NotifierError("timeout")`.
  - **Text:** `notify` sends `format_alert(message)` with `link_preview=True`; `notify_system` sends the raw text with `link_preview=True`.
  - **Errors:** any exception from `send_message` becomes `NotifierError(type(e).__name__)`. Class names in `NEEDS_START = frozenset({"UserIsBlockedError", "PeerIdInvalidError", "ValueError"})` record `needs_start` with detail `None`; any other records `error` with the class name. A successful send records `ok`.
  - **`async aclose() -> None`:** cancels a running login task (awaiting it with `contextlib.suppress(asyncio.CancelledError)`), then `client.disconnect()` inside `contextlib.suppress(Exception)`.
  - **The token** goes only to `client.start`. It never appears in any message, log or state detail.

**Steps:**
- [ ] Write the failing config tests:
  - the default is `log`;
  - `telegram` without a token raises;
  - `telegram` with a token and a chat id parses (including a negative group id);
  - a bad `ALERT_CHAT_ID` raises;
  - `repr` hides the token;
  - `email` is still rejected as an unknown notifier.
- [ ] Write the failing `send_with_retry` test: a notifier with `attempt_timeout = 0.01` whose `notify` awaits `asyncio.sleep(0.05)` fails with `"timeout after 0.01s"`; one without the attribute still uses the default.
- [ ] Write the failing contract tests for `NotifierStateStore`, on both the fake and SQLite:
  - set and get;
  - a repeated set with the same values does not change `updated_at`; a changed detail does;
  - `set_chat_id` then `get_chat_id`; a later `set` keeps the chat id; `set_chat_id` on a missing row is a no-op.
- [ ] Write the failing adapter tests, with `FakeBotClient` (records calls, scriptable to raise on `start` or `send_message`, optional awaitable gate on `start`) and a fake `monotonic` that the fake `sleep` advances:
  - the text and the preview for `notify` and `notify_system`;
  - three concurrent sends sleep 1 s and then 2 s (in fake time);
  - a burst of 10 sends delivers all 10, in order;
  - each send error becomes a `NotifierError` with the class name;
  - `ValueError`, `PeerIdInvalidError` and `UserIsBlockedError` (fake exception classes with those names) record `needs_start`; another class records `error`;
  - after a failed login, a send within 60 s raises `bot_unavailable` without calling `start` again, and one after 60 s calls it;
  - five concurrent sends during a gated login call `start` once;
  - cancelling one waiter during a gated login does not cancel the login;
  - a login that never finishes fails after `LOGIN_TIMEOUT_S` with state `error (TimeoutError)` and calls `disconnect`;
  - `notify_system` with a hung send raises `NotifierError("timeout")`;
  - no chat raises `no_chat`;
  - with a token string `"123:SECRET-TOKEN"` and a fake `start` that raises `RuntimeError("bad 123:SECRET-TOKEN")`: the token is in no log record (message and `extra`), no raised exception text and no state detail;
  - `aclose` cancels a pending login and disconnects.
- [ ] Implement. Run the tests green, run the full checks, and commit `feat(alerting): telegram bot notifier, notifier state and config`.

### Task 2: Wiring, status line, notify-test and .env.example
Spec §2 (Client, Alert first, CLI, Compose, Status line), §4.

**Files:**
- Modify:
  - `velkgram/ingestion/adapters/telethon/client.py`: add `TelethonBotClient` and `build_bot_client(settings) -> TelethonBotClient`;
  - `velkgram/apps/collector/main.py`;
  - `velkgram/apps/cli.py`: add `cmd_notify_test`, registered in `COMMANDS` and the parser, plus a module-level `_make_clients(settings)` factory; import Telethon lazily inside it, like the existing collector command;
  - `velkgram/ingestion/web/router.py` and `status.html`;
  - `velkgram/apps/web/main.py`: a helper that reads `SqliteNotifierStateStore(conn).get()`;
  - `.env.example`: `NOTIFIER=log`, an empty `ALERT_BOT_TOKEN=`, an empty `ALERT_CHAT_ID=`, with English comments.
- Tests:
  - `tests/apps/test_collector_runtime.py` (extend);
  - `tests/apps/test_cli_notify_test.py`;
  - `tests/ingestion/web/test_status_router.py`.

**Interfaces:**
- **Consumes** everything from Task 1.
- **Produces:**
  - **`TelethonBotClient(client: TelegramClient)`** satisfies `BotClient`: `start` awaits `client.start(bot_token=...)`; `send_message` awaits `client.send_message(chat_id, text, link_preview=link_preview)` and drops the return value; `disconnect` awaits `client.disconnect()`. Use `# type: ignore[misc]` on the Telethon awaits as the existing code does.
  - **`build_bot_client(settings)`** validates `tg_api_id` and `tg_api_hash` like `build_client` (raises `ValueError`), and builds `TelegramClient(StringSession(""), api_id, api_hash, flood_sleep_threshold=0)` wrapped in `TelethonBotClient`.
  - **`run(settings, client, notifier=None, sleep=asyncio.sleep, *, bot_client: BotClient | None = None)`.** The positional signature is unchanged.
    - When `notifier` is given, nothing new happens: no state write, no `get_me`. Existing tests inject `notifier=FakeNotifier()` with a `MagicMock` client whose `get_me` is not awaitable, and `test_startup_order` checks `names[:4]`; both must keep passing unchanged.
    - When `notifier is None` and `settings.notifier == "log"`: `LogNotifier`, and `SqliteNotifierStateStore(conn).set(disabled, None, now)` right after migrations.
    - When `notifier is None` and `settings.notifier == "telegram"`: right after migrations, build `TelegramBotNotifier(bot_client or build_bot_client(settings), token, chat_id=resolve, state=SqliteNotifierStateStore(conn), clock=clock)` and call `begin_login()` before `client.connect()`.
    - `resolve()` returns `settings.alert_chat_id`, else the id held in a small mutable holder, else `state.get_chat_id()`.
    - After `is_user_authorized()` is true, and only on the telegram branch without `ALERT_CHAT_ID`: `me = await client.get_me()` inside `try/except Exception` (log `get_me_failed` with the class name and continue); on success, put `me.id` in the holder and call `state.set_chat_id(me.id)`.
    - In `finally`, after the existing cleanup, `await notifier.aclose()` when a `TelegramBotNotifier` was built here.
  - **`velkgram notify-test`:**
    - loads settings, applies migrations, and refuses with exit 2 and a message when `NOTIFIER` is not `telegram`;
    - `_make_clients(settings) -> tuple[TelegramClient | None, BotClient]`: the user client (`build_client`) only when `ALERT_CHAT_ID` is unset, and `build_bot_client(settings)`;
    - chat: `ALERT_CHAT_ID`; else connect the user client, `get_me()` if authorized, store it with `set_chat_id`, disconnect; else the stored chat id;
    - sends `Velkgram: teste de alerta ✅` through `TelegramBotNotifier.notify_system`;
    - prints `enviado` and exits 0, or prints `falhou: <ErrorClass or NotifierError text>` and exits 1;
    - always calls `aclose()`.
  - **`build_router(..., notifier_status: Callable[[sqlite3.Connection], dict[str, object] | None] | None = None)`.** The status page shows exactly one of the four spec §2 lines from `{"status": ..., "detail": ...}`, and no line when the callable is not wired or returns `None` (no row).

**Steps:**
- [ ] Write the failing wiring tests in `tests/apps/test_collector_runtime.py`, with `Settings(db_path=tmp, notifier="telegram", alert_bot_token="123:SECRET-TOKEN")`, a fake user client (async `get_me` returning an object with `id`) and `bot_client=FakeBotClient()`; the evaluator and retry delays use the existing fake sleep:
  - an offer alert reaches the fake bot end to end, addressed to the `get_me` id;
  - with `alert_chat_id` set, `get_me` is not called and the alert goes there;
  - with `get_me` raising and a stored chat id, the alert goes to the stored id;
  - a fake bot whose `start` raises still lets ingestion store messages; the alert becomes `failed`; the state is `error`; the token is in no log record;
  - `NOTIFIER=log` without an injected notifier gives the `disabled` state;
  - `aclose` runs on shutdown (the fake bot sees `disconnect`).
- [ ] Write the failing CLI tests, monkeypatching `_make_clients`:
  - success prints `enviado`, exit 0;
  - a bot failure prints `falhou: ...`, exit 1;
  - `NOTIFIER=log` gives exit 2;
  - the token appears in neither stdout nor stderr.
- [ ] Write the failing status page tests: all four lines, the detail in the error line, no line without a row, and no line when the callable isn't wired.
- [ ] Implement. Run the tests green, then the full checks and `docker compose config -q`. Commit `feat(apps): wire telegram notifier, notify-test command and status line`.

## Execution
- Run Task 1, then Task 2. The two are reviewed together by one fresh, context-free reviewer, followed by a fix round if needed. Then one final whole-branch review.
- **Real check (controller):** with the owner's `.env`, run `velkgram notify-test` inside the collector container, then watch one real alert arrive. This requires the owner's OK, because it uses their real bot and session.
