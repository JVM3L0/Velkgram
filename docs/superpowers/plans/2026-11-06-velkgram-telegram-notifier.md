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
  - the Telethon bot wrapper lives in `velkgram/ingestion/adapters/telethon/client.py` and never imports alerting (it satisfies `BotClient` structurally, so its parameter names must match the protocol exactly);
  - only `velkgram/apps/` builds clients and wires adapters;
  - ingestion's status page gets plain data through an injected callable.
- Alert first:
  - the bot never blocks the collector's startup or ingestion;
  - a send failure raises `NotifierError`, and the existing retry and failed handling take over.
- The token never appears in logs, exception messages, exception chains, the state detail or any rendered page. Tests prove it. Login failures are logged with `log.warning("bot_login_failed", extra={"error": type(e).__name__})`, never `log.exception` and never `str(e)`. Every `NotifierError` raised from a caught exception uses `from None`.
- No test touches the network or a real Telegram client. Use fakes. Whenever a test injects a fake `sleep`, that fake sleep advances the fake `monotonic` by the slept amount.
- TDD: run each test red before implementing. Full checks before each commit: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports && uv run pytest -q`. Run pyright early on the config change (Literal narrowing).
- Never use `.env` or `data/velkgram.db` in tests. Never commit secrets. Never push.
- Load the skills `velkgram-architecture`, `velkgram-conventions`, `velkgram-testing` and `velkgram-task`.
- Subagents run on Sonnet or Haiku. Implementers never dispatch subagents and take no screenshots.

## Review Focus
1. **The owner never pressed Start, or blocked the bot.** Telethon raises `ValueError` (unresolvable peer), `PeerIdInvalidError` or `UserIsBlockedError`; all three give `needs_start`, and nothing crashes. Task 1.
2. **Bad token, revoked token or no network.** Ingestion keeps running, alerts are `failed` and retried later, the bot login is retried lazily, concurrent sends never start two logins, a hung disconnect never wedges future logins, and a lost bot authorization triggers a new login. Tasks 1 and 2.
3. **Timeouts and the fatal alert.** Pacing plus login fit inside the notifier's 10 s attempt budget, which `send_with_retry` honors. `notify_system` is bounded to 10 s and is never skipped by the login throttle, so the "Velkgram parou" alert is attempted and `fatal()` still writes its heartbeat. Known cost: with Telegram hung, one alert can hold the serial worker for up to 3 × 10 s plus retry delays. Task 1.
4. **Token leakage.** The token stays out of every log record, error message, exception chain, state detail, CLI output and the Status page, including when the fake login raises an exception whose text contains the token. Tasks 1 and 2.
5. **The chat goes to the right person, even when the user session is dead, and diagnostics never touch the live session.** Order: `ALERT_CHAT_ID`, this run's `get_me()`, the stored chat id. `notify-test` never connects the user session. Task 2.

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
  - `velkgram/alerting/ports/notifier_state.py` (holds `NotifierStatus` and `NotifierStateStore`);
  - `velkgram/alerting/adapters/sqlite/notifier_state.py` (`SqliteNotifierStateStore(conn)`).
- Add the `NotifierStateStore` fake and a `FakeBotClient` to `tests/fakes/`.
- Tests:
  - `tests/shared/test_config.py`;
  - the existing `send_with_retry` test file under `tests/alerting/`, or `tests/alerting/services/test_notify.py` if there is none;
  - `tests/alerting/adapters/test_notify_telegram.py`;
  - `tests/contracts/test_notifier_state.py`.

**Interfaces (produces):**
- **`Settings`** gains these fields:
  - `notifier: Literal["log", "telegram"]`;
  - `alert_bot_token: str | None = None`;
  - `alert_chat_id: int | None = None`.

  `load_settings` reads `NOTIFIER` (empty means `log`), `ALERT_BOT_TOKEN` and `ALERT_CHAT_ID`. The existing `unknown NOTIFIER` guard accepts exactly `log` and `telegram` (use explicit branches if pyright doesn't narrow a membership test to the Literal). `telegram` without a token raises `ValueError("ALERT_BOT_TOKEN is required when NOTIFIER=telegram")`. A non-integer `ALERT_CHAT_ID` raises `ValueError`. The hand-written `__repr__` masks the token with the existing `mask` and shows `alert_chat_id` as is.
- **`send_with_retry`** keeps its signature. Each attempt uses the notifier's `attempt_timeout` attribute when it exists and is an `int | float`, else the `attempt_timeout` argument; the timeout error text uses the value actually applied.
- **`NotifierStatus`** is a `StrEnum`: `ok`, `needs_start`, `error`, `disabled`.
- **`NotifierStateStore` (Protocol)** has:
  - `set(status: NotifierStatus, detail: str | None, at: datetime) -> None`, which writes only when the status or the detail changed, and never touches `chat_id`;
  - `get() -> tuple[NotifierStatus, str | None, datetime] | None`;
  - `set_chat_id(chat_id: int) -> None`, which updates only `chat_id` and is a no-op on a missing row;
  - `get_chat_id() -> int | None` (`None` without a row).

  The migration creates `notifier_state(id INTEGER PRIMARY KEY CHECK (id = 1), status TEXT NOT NULL CHECK (status IN ('ok','needs_start','error','disabled')), detail TEXT, chat_id INTEGER, updated_at TEXT NOT NULL)`, with no BEGIN or COMMIT. It has an SQLite implementation and a fake.
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

  Class attributes, always read through `self.` so tests can override them on the instance: `attempt_timeout = 10.0`, `LOGIN_TIMEOUT_S = 8.0`, `LOGIN_RETRY_S = 60.0`, `SYSTEM_TIMEOUT_S = 10.0`, `DISCONNECT_TIMEOUT_S = 2.0`, `MIN_INTERVAL_S = 1.0`. Name sets: `NEEDS_START = frozenset({"UserIsBlockedError", "PeerIdInvalidError", "ValueError"})`, `LOGIN_LOST = frozenset({"AuthKeyUnregisteredError", "AccessTokenExpiredError", "AccessTokenInvalidError", "AuthKeyDuplicatedError", "SessionRevokedError"})`.

  Internal state: `_started = False`, `_login_task: asyncio.Task[None] | None = None`, `_next_login_at: float | None = None`, `_last_send_at: float | None = None`. `None` means "never", so the first login and the first send are never throttled whatever `monotonic()` returns.

  - **`begin_login(force: bool = False) -> None`:** never awaits. Does nothing when `_started` or when a login task exists and is not done. Otherwise, unless `force`, does nothing while `monotonic() < _next_login_at`. Else sets `_next_login_at = monotonic() + LOGIN_RETRY_S` and creates the login task. The collector calls it once at startup.
  - **The login task** catches every `Exception` itself and never re-raises. It runs `client.start(token)` inside `asyncio.timeout(self.LOGIN_TIMEOUT_S)`. On success: `_started = True`, record `ok`. On failure: record `error` with the class name only (`TimeoutError` on timeout); log `bot_login_failed` with the class name; for a `FloodWaitError`-like error with an int `seconds` attribute, push `_next_login_at` to at least `now + seconds`; then `client.disconnect()` inside `asyncio.timeout(self.DISCONNECT_TIMEOUT_S)` and `contextlib.suppress(Exception)`.
  - **`async ensure_started(force: bool = False) -> bool`:** returns `True` when `_started`. Otherwise calls `begin_login(force)`; if a login task is not done, awaits it through `asyncio.shield` (a cancelled caller never cancels the login). Returns `_started`. N concurrent callers cause one `client.start` call.
  - **`notify(message)`:** `ensure_started()`; if `False`, raise `NotifierError("bot_unavailable")`. Then the shared send path with `format_alert(message)`.
  - **`notify_system(text)`:** the whole call runs inside `asyncio.timeout(self.SYSTEM_TIMEOUT_S)`, and `TimeoutError` becomes `NotifierError("timeout") from None`. It calls `ensure_started(force=True)`, so the 60 s throttle never skips a system alert. Then the shared send path with `text`.
  - **Shared send path:** a missing chat id records `error` with detail `sem chat` and raises `NotifierError("no_chat")`. Then take the lock; if `_last_send_at` is set, sleep until `MIN_INTERVAL_S` after it; set `_last_send_at = monotonic()`; call `send_message(chat_id, text, link_preview=True)`. Success records `ok`. Any exception becomes `NotifierError(type(e).__name__) from None`; a name in `NEEDS_START` records `needs_start` with detail `None`; any other records `error` with the class name; a name in `LOGIN_LOST` also sets `_started = False`.
  - **`async aclose() -> None`:** cancels a running login task and awaits it under `contextlib.suppress(asyncio.CancelledError)`, then `client.disconnect()` inside `asyncio.timeout(self.DISCONNECT_TIMEOUT_S)` and `contextlib.suppress(Exception)`. A shielded waiter at that moment gets `CancelledError`; that is acceptable at shutdown.
  - **The token** goes only to `client.start`. It never appears in any message, log or state detail.

**Steps:**
- [ ] Write the failing config tests:
  - the default is `log`, and an empty `NOTIFIER` is `log`;
  - `telegram` without a token raises;
  - `telegram` with a token and a chat id parses (including a negative group id);
  - a bad `ALERT_CHAT_ID` raises;
  - `repr` hides the token;
  - `email` is still rejected as an unknown notifier.
- [ ] Write the failing `send_with_retry` test: a notifier with `attempt_timeout = 0.01` whose `notify` awaits `asyncio.sleep(0.05)` fails with `"timeout after 0.01s"`; one without the attribute still uses the default.
- [ ] Write the failing contract tests for `NotifierStateStore`, on both the fake and SQLite:
  - set and get;
  - a repeated set with the same values does not change `updated_at`; a changed detail does;
  - `set_chat_id` then `get_chat_id`; a later `set` keeps the chat id; `set_chat_id` on a missing row is a no-op and `get_chat_id` is `None`.
- [ ] Write the failing adapter tests. `FakeBotClient` records calls (and the fake `monotonic` value at each `send_message`), can be scripted to raise on `start` or `send_message`, and can gate `start`, `send_message` or `disconnect` on an `asyncio.Event`. Timeout tests set the matching `*_S` attribute to `0.05` on the instance and run on real loop time.
  - the text and the preview for `notify` and `notify_system`;
  - three concurrent sends start at fake monotonic `0.0, 1.0, 2.0`, and the recorded sleeps are `[1.0, 1.0]`;
  - a burst of 10 sends delivers all 10, in order;
  - each send error becomes a `NotifierError` with the class name, with `__cause__ is None` and `__suppress_context__` true;
  - `ValueError`, `PeerIdInvalidError` and `UserIsBlockedError` (fake exception classes with those names) record `needs_start`; another class records `error`;
  - after a failed login at fake time 0, `notify` at 30 raises `bot_unavailable` without calling `start` again, and `notify` at exactly 60 calls it;
  - after a failed login at fake time 0, `notify_system` at 5 calls `start` again;
  - five concurrent sends during a gated login call `start` once;
  - cancelling one waiter during a gated login does not cancel the login;
  - a login that never finishes fails after `LOGIN_TIMEOUT_S` with state `error (TimeoutError)` and calls `disconnect`;
  - a hung `disconnect` after a failed login does not block the next login attempt;
  - a send raising an `AuthKeyUnregisteredError`-named error makes the next send (after the throttle) call `start` again;
  - `notify_system` with a hung send raises `NotifierError("timeout")`;
  - no chat raises `no_chat` and records `error (sem chat)`;
  - with the token `"123:SECRET-TOKEN"` and a fake `start` raising `RuntimeError("bad 123:SECRET-TOKEN")`: the token is not in `caplog.text`, not in any value of any record's `__dict__`, not in the raised exception's text or chain, and not in the state detail;
  - `aclose` cancels a pending login and disconnects.
- [ ] Implement. Run the tests green, run the full checks, and commit `feat(alerting): telegram bot notifier, notifier state and config`.

### Task 2: Wiring, status line, notify-test and .env.example
Spec §2 (Client, Alert first, CLI, Compose, Status line), §4.

**Files:**
- Modify:
  - `velkgram/ingestion/adapters/telethon/client.py`: add `TelethonBotClient` and `build_bot_client(settings) -> TelethonBotClient`;
  - `velkgram/apps/collector/main.py`: add `build_notifier` and `remember_chat`, and use them in `run()`;
  - `velkgram/apps/cli.py`: add `cmd_notify_test`, registered in `COMMANDS` and the parser, plus a module-level `_make_bot_client(settings)` factory that imports Telethon lazily, like the existing collector command;
  - `velkgram/ingestion/web/router.py` and `status.html`;
  - `velkgram/apps/web/main.py`: a `_notifier_status(conn)` helper;
  - `.env.example`: `NOTIFIER=log` (with a comment that empty means `log`), an empty `ALERT_BOT_TOKEN=`, an empty `ALERT_CHAT_ID=` (with a comment that a group must contain the bot), in English.
- Tests:
  - `tests/apps/test_collector_runtime.py` (extend);
  - `tests/apps/test_collector_assembly.py` (extend, for the end-to-end alert);
  - `tests/apps/test_cli_notify_test.py`, plus `notify-test` added to the list in `tests/apps/test_cli.py::test_cli_help_lists_subcommands`;
  - `tests/ingestion/web/test_status_router.py`.

**Interfaces:**
- **Consumes** everything from Task 1.
- **Produces:**
  - **`TelethonBotClient(client: TelegramClient)`** satisfies `BotClient` with the exact parameter names `bot_token`, `chat_id`, `text`, `link_preview`. `start` awaits `client.start(bot_token=bot_token)`; `send_message` awaits `client.send_message(chat_id, text, link_preview=link_preview)` and drops the return value; `disconnect` awaits `client.disconnect()`. Use `# type: ignore[misc]` on the Telethon awaits as the existing code does.
  - **`build_bot_client(settings)`** validates `tg_api_id` and `tg_api_hash` like `build_client` (raises `ValueError`), and builds `TelegramClient(StringSession(""), api_id, api_hash, flood_sleep_threshold=0)` wrapped in `TelethonBotClient`.
  - **`ChatHolder`:** a small dataclass `ChatHolder(override: int | None, current: int | None = None)` with a `resolve(state: NotifierStateStore) -> int | None` that returns `override`, else `current`, else `state.get_chat_id()`.
  - **`build_notifier(settings, conn, clock, bot_client: BotClient | None = None) -> tuple[Notifier, TelegramBotNotifier | None, ChatHolder | None]`:**
    - `log`: records `disabled` and returns `(LogNotifier(), None, None)`;
    - `telegram`: when no row exists, records `error` with detail `iniciando`, so `set_chat_id` always has a row. Then builds `TelegramBotNotifier(bot_client or build_bot_client(settings), token, chat_id=lambda: holder.resolve(state), state=SqliteNotifierStateStore(conn), clock=clock)` and returns `(bot, bot, holder)`. It does not start the login.
  - **`async remember_chat(client, holder: ChatHolder, state: NotifierStateStore) -> None`:** does nothing when `holder.override` is set. Otherwise runs `await client.get_me()` inside `asyncio.timeout(5)` and `try/except Exception`; a failure logs `get_me_failed` with the class name. On success it sets `holder.current = me.id` and calls `state.set_chat_id(me.id)`.
  - **`run(settings, client, notifier=None, sleep=asyncio.sleep, *, bot_client: BotClient | None = None)`.** The positional signature is unchanged.
    - When `notifier` is given, nothing new happens: no state write, no `get_me`. Existing tests inject `notifier=FakeNotifier()` with a `MagicMock` client whose `get_me` is not awaitable, and `test_startup_order` checks `names[:4]`; both keep passing unchanged.
    - When `notifier is None`, `build_notifier(...)` runs right after migrations and before `Collector(...)`.
    - Inside the `try`, before `client.connect()`: `bot.begin_login()` when a bot was built.
    - After `is_user_authorized()` is true, before `warm_entity_cache`: `await remember_chat(client, holder, state)` when a holder exists.
    - In `finally`, after the existing cleanup: `await bot.aclose()` when a bot was built.
  - **`velkgram notify-test`:**
    - loads settings, calls `configure_logging(settings.log_level)`, applies migrations, and exits 2 with a message when `NOTIFIER` is not `telegram`;
    - chat: `ALERT_CHAT_ID`, else the stored chat id. It never connects the user session: a second connection on the live collector's `TG_SESSION` can raise `AuthKeyDuplicatedError` and stop the collector. With no chat it prints `falhou: sem chat (defina ALERT_CHAT_ID ou rode o coletor uma vez)` and exits 1;
    - builds the notifier like the collector does (`_make_bot_client(settings)`, the same state store, a `ChatHolder`), records `error`/`iniciando` when no row exists, and sends `Velkgram: teste de alerta ✅` through `notify_system`;
    - prints `enviado` and exits 0. On `NotifierError` it prints `falhou: <error text>`, plus ` (<state detail>)` when the state detail is set and differs, for example `falhou: bot_unavailable (AccessTokenInvalidError)`, and exits 1;
    - always calls `aclose()`;
    - `_make_bot_client`'s return annotation is `BotClient`, so the module needs no Telethon import at load time.
  - **`build_router(..., notifier_status: Callable[[sqlite3.Connection], dict[str, object] | None] | None = None)`.** `_notifier_status(conn)` returns `{"status": status.value, "detail": detail}`, or `None` when there is no row or the table does not exist (`sqlite3.OperationalError`). The status page shows exactly one of the four spec §2 lines, and no line when the callable is not wired or returns `None`.

**Steps:**
- [ ] Write the failing wiring tests:
  - `build_notifier` with `log` records `disabled` and returns a `LogNotifier`;
  - `build_notifier` with `telegram` and `FakeBotClient` records `error (iniciando)` on an empty table, and keeps an existing row as is;
  - `remember_chat` with a fake user client (async `get_me` returning an object with `id`) stores the id; with `ALERT_CHAT_ID` set it never calls `get_me`; with `get_me` raising or hanging (the test patches the 5 s bound to a small value or uses a gate plus `asyncio.timeout` override) it logs and keeps the stored chat id;
  - in `tests/apps/test_collector_assembly.py`, using its existing `Env`: an offer alert evaluated with a `TelegramBotNotifier` over `FakeBotClient` reaches the fake bot, addressed to the resolved chat; with a failing fake `start`, the alert becomes `failed`, the state is `error`, and the token is in no log record;
  - one thin `run()` test with `NOTIFIER=log` and no injected notifier: the state is `disabled`; one with `telegram` and `bot_client=FakeBotClient()`: `aclose` runs on shutdown (the fake sees `disconnect`). Drive `run()` as the existing runtime tests do (create a task, then cancel).
- [ ] Write the failing CLI tests (sync tests; the command uses `asyncio.run`), monkeypatching `_make_bot_client`:
  - success prints `enviado`, exit 0;
  - a send failure prints `falhou: ...`, exit 1; a failed login prints the class from the state detail;
  - no chat prints the `sem chat` message, exit 1;
  - `NOTIFIER=log` gives exit 2;
  - the token appears in neither stdout nor stderr.
- [ ] Write the failing status page tests: all four lines, the detail in the error line, no line without a row, and no line when the callable isn't wired.
- [ ] Implement. Run the tests green, then the full checks and `docker compose config -q`. Commit `feat(apps): wire telegram notifier, notify-test command and status line`.

## Execution
- Run Task 1, then Task 2. The two are reviewed together by one fresh, context-free reviewer, followed by a fix round if needed. Then one final whole-branch review.
- **Real check (controller):** with the owner's `.env`, run `velkgram notify-test` after the collector has run once (so the chat id is stored) or with `ALERT_CHAT_ID` set, then watch one real alert arrive. This requires the owner's OK, because it uses their real bot.
