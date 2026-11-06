# Link Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A separate `enricher` process follows offer links and records the store, the product id, and, where cheap, a title and an image. The data feeds store fixes, feed photos, the "visto em N canais" collapse and the "outro produto" chip.

**Architecture:** Everything lives in the offers module:
- pure per-store rules and URL helpers (domain);
- an httpx fetcher adapter behind a `Fetcher` port;
- an enrichment loop service with its own link repository;
- query changes in the existing SQLite offers queries.

The collector and `OfferBuilder` are untouched.

**Tech Stack:** Python 3.13, uv, SQLite (WAL), httpx (moved to runtime), FastAPI + Jinja2 + HTMX, pytest, import-linter.

**Spec:** `docs/superpowers/specs/2026-11-05-velkgram-link-enrichment-design.md`. Each task cites the sections it implements. Values in the spec are binding unless this plan states otherwise. The plan wins on details.

## Global Constraints
- **Language:** Artifacts are in English. User-facing text is in pt-BR.
- **New dependencies:** Only `httpx` moves from the dev group to `[project].dependencies`, done in Task 3. Refresh `uv.lock` with `uv lock`. Nothing else is added: no brotli, no lxml, no BeautifulSoup.
- **import-linter:** `uv run lint-imports` must keep all 10 contracts. Task 1 adds `"httpx"` to the `forbidden_modules` of the contracts "domain is pure (rule 1)" and "services do no I/O (rule 2)" in `pyproject.toml`. That keeps the count at 10.
- **Module rules:** Only `velkgram/apps/` imports adapters, and no other module reads `product_links`.
- **Hot path:** No change to the collector, `OfferBuilder`, alerting, or v1 latency.
- **Logs never carry a full URL, a query string, or exception text from httpx.** They carry only host, status and exception class name. In the enricher, the `httpx` and `httpcore` loggers are set to WARNING.
- **TDD:** Write the failing test first, and run it red. Every new port or repository method gets a fake in `tests/fakes/`, plus contract tests that run on both the fake and SQLite.
- **Tests never touch the internet:**
  - Use `httpx.MockTransport`, or a stdlib `http.server` on localhost.
  - Fixtures are trimmed real pages under `tests/fixtures/links/`, built from `/tmp/claude-1000/-home-velkhano-projects-Velkgram/18085f53-c9e3-4fc5-a0b6-b5697ee04b41/scratchpad/spike-links/*.html`, with tokens and query strings scrubbed.
- **Checks before every commit:** `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports && uv run pytest -q`.
- **Never use** `.env` or `data/velkgram.db` in tests. Never commit secrets or DB files. Never push.
- **Constants (spec §5):**
  - redirects: at most 5;
  - timeouts: 10 s per request and 30 s per chain;
  - body budgets by host:

    | Host | Budget |
    |---|---|
    | Amazon | 512 KB |
    | Mercado Livre | 512 KB |
    | KaBuM! | 16 KB |
    | Other hosts | 64 KB |
    | AliExpress, Shopee, Magalu | 0 |
  - throttle: 2 s per host, on every hop;
  - pause on 403/429: 30 min per host;
  - retries: after 5 min, 30 min and 6 h, then `failed` after the 4th attempt;
  - `blocked` rows: retried once after 24 h;
  - discovery: batches of 50, idle sleep of at most 10 s;
  - titles: capped at 200 chars;
  - dominant product: at least 3 keyed matches, at least 60 %, strictly ahead of the runner-up;
  - collapse window: 24 h;
  - feed latency: at most 150 ms on the volume fixture.
- **Skills:** Each task loads `velkgram-architecture`, `velkgram-conventions`, `velkgram-testing` and `velkgram-task`.
- **Subagents:** Sonnet or Haiku only. Implementers never dispatch subagents and never take screenshots.

## Review Focus
1. **A re-ingest wipes a fixed store.** Edits, redelivery and `rebuild-offers` must keep a store that the enricher fixed. Task 2 owns this.
2. **Affiliate tokens leak.** No log record, stored `final_url` or rendered page may contain a link's query string. Tasks 3 and 4 own this.
3. **The enricher starves the collector.** A concurrent `upsert` must never hit "database is locked" while the enricher runs. Task 2 tests it with a real second connection; Task 4 tests the loop.
4. **The feed collapse breaks paging or "N novas".** Collapsed offers must never repeat or vanish across pages, and `count_feed_after` must agree with the list. Task 5 owns this.
5. **A wrong product photo on a card.** Images only appear for `kind = product` with a product id. A `/social/` page without `item_id` shows no image. Tasks 1 and 6 own this.

---

### Task 1: Domain rules, URL helpers and dominant product
Spec §3, §4 (module rules), §5.3, §5.5 (the function).

**Files**
- Create:
  - `velkgram/offers/domain/urls.py`: `strip_query`, `is_safe_url`, `is_safe_https_url`, `host_of`.
  - `velkgram/offers/domain/links.py`: `FetchPlan`, `FetchOutcome`, `LinkInfo`, `fetch_plan`, `budget_for`, `resolve`, `resolve_url_only`.
  - `velkgram/offers/domain/dominant.py`: `dominant_product`, `dominant_from_counts`.
  - `tests/fixtures/links/*.html`: trimmed, scrubbed real pages.
- Modify:
  - `velkgram/offers/web/format.py`: `safe_href` delegates to `is_safe_url` and keeps its current behavior.
  - `pyproject.toml`: add `"httpx"` to the `forbidden_modules` of the "domain is pure (rule 1)" and "services do no I/O (rule 2)" contracts.
- Test: `tests/offers/domain/test_urls.py`, `tests/offers/domain/test_links.py`, `tests/offers/domain/test_dominant.py`.

**Interfaces (produces)**
- **URL helpers** (`urls.py`):
  - `strip_query(url: str) -> str` drops the query and the fragment.
  - `is_safe_url(url: str | None) -> bool` is true only for http and https. This is the current `safe_href` rule.
  - `is_safe_https_url(url: str | None) -> bool` is true only for https.
  - `host_of(url: str) -> str` returns the lowercase host, or `""`.
- **Data types** (`links.py`), all frozen dataclasses:
  - `FetchPlan(follow: bool, first_hop_only: bool, body_budget: int | None)`. A budget of `None` means the per-host budget is decided at the final hop through `budget_for`.
  - `FetchOutcome(final_url: str, hops: tuple[str, ...], status: int | Literal["invalid", "error", "paused"], content_type: str | None, body: str | None, answered_by: str)`. `answered_by` is the host that gave the final status.
  - `LinkInfo(store: str | None, product_id: str | None, title: str | None, image_url: str | None, kind: Literal["product", "not_product", "unknown"])`.
- **`fetch_plan(url: str) -> FetchPlan`:**

  | URL | `follow` | `first_hop_only` | `body_budget` |
  |---|---|---|---|
  | Amazon `/dp/` or `/gp/…` (direct) | False | False | 512 KB |
  | `s.click.aliexpress.com` | False | True | 0 |
  | `s.shopee.com.br` | True | False | 0 |
  | `meli.la` | True | False | 512 KB |
  | `cutt.ly`, `tidd.ly`, `bit.ly`, `go.promotom.com.br`, `link.amazon` | True | False | None |
  | anything else | True | False | 64 KB |

- **`budget_for(url: str) -> int`** gives the per-host budget from the constants table, by final host.
- **`resolve(original_url: str, outcome: FetchOutcome) -> LinkInfo`** implements spec §5.3.
  - The store comes from the existing `store_of` in `offers/domain/stores.py`; don't duplicate it.
  - Normalize ids: an ASIN is uppercase, a Mercado Livre id is `MLB<digits>`, and a Shopee id is `<shopid>.<itemid>`.
  - An Amazon captcha or "Robot Check" `<title>` counts as blocked, giving kind `unknown` with no title and no image.
- **`resolve_url_only(url: str) -> LinkInfo | None`** returns store and id from the URL alone, as `kind="product"` with no title or image, or None. The reuse path uses it, so a URL that was never fetched is never guessed `not_product`.
- **`dominant_product(keys: Sequence[tuple[str, str] | None]) -> tuple[str, str] | None`** implements spec §5.5.
- **`dominant_from_counts(counts: Sequence[tuple[tuple[str, str], int]], keyed_total: int) -> tuple[str, str] | None`** applies the same rule to SQL counts, top first. `dominant_product` delegates to it.

**Steps**
- [ ] **Fixtures.** From the spike pages, keep `<head>` and the JSON fragments the rules need: Amazon `hiRes` and Mercado Livre `item_id`. Replace every query string and token with `X`. Keep each file ≤ 30 KB.
- [ ] **Failing table tests** (`test_links.py`), one row per spec §8 domain case:
  - Amazon: ASIN, the prefix and suffix stripped, `hiRes`, and a captcha page.
  - KaBuM!: `og:` tags.
  - Mercado Livre social page with `item_id`, and the title suffixes ` - R$ 16,14`, ` - R$ 1.299,00` and ` - R$ 1.299`.
  - Mercado Livre social page without `item_id`, which gives `not_product` with no image.
  - AliExpress: `productId` in the first hop.
  - Shopee: `/slug/123/456` gives `123.456`.
  - Magalu: `/magazinex/p/240162700/` with status 403 gives `product` with id `240162700`.
  - `link.amazon` and `go.promotom /promocao/` give `not_product`.
  - An unknown host with `og:` tags gives `unknown` with a title.
  - A cutt.ly interstitial (200, no hops) gives `unknown`.
  - An `http://` or `javascript:` image gives None.
  - A 250-character title is capped at 200.
  - Garbage input never raises: a truncated tag, a NUL byte, a 1 MB attribute, an empty body.
- [ ] **Failing tests for `fetch_plan`, `budget_for`, `resolve_url_only` and the URL helpers**, including a `safe_href` regression.
- [ ] **Failing `dominant_product` tests:**
  - `[A,A,A,B]` gives A;
  - `[A,A,B,B]` gives None;
  - `[A,A]` gives None;
  - `[A,A,B,None,None]` gives A;
  - `[A,B,C]` gives None.

  Also test that `dominant_from_counts` agrees with `dominant_product` on the same data.
- [ ] Run the tests red, implement, run them green, then run the full checks.
- [ ] Commit `feat(offers): link rules, URL helpers and dominant product`.

### Task 2: Data — migration, link repository, store-preserving upsert
Spec §5.1, §5.4 (writes), §5.7 (heartbeat), §6, §7 (locks).

**Files**
- Create:
  - `velkgram/offers/migrations/006_product_links.sql`;
  - `velkgram/offers/ports/links.py`;
  - `velkgram/offers/adapters/sqlite/links.py`.
- Modify:
  - `velkgram/offers/adapters/sqlite/repository.py` (`_UPSERT`);
  - `tests/fakes/repositories.py`;
  - `velkgram/offers/__init__.py` (export `LinkRow`, `LinkRepository`, `EnrichHeartbeat`).
- Test: `tests/contracts/test_link_repository.py`, `tests/contracts/test_offer_repository.py`, `tests/offers/adapters/test_links_concurrency.py`, and the migration test.

**Interfaces (produces)**
- **Migration**, with no BEGIN or COMMIT:
  - `product_links`, as in spec §6, plus the columns `offer_posted_at TEXT NOT NULL` (the newest posting time of its offers when discovered; it is not refreshed later, which is accepted), `host TEXT NOT NULL` (`host_of(url)`), `final_host TEXT` (set on save) and `blocks INTEGER NOT NULL DEFAULT 0` (403/429 count, separate from `attempts`).
  - Indexes on `product_links (status, next_try_at)`, `product_links (offer_posted_at)`, `product_links (store, product_id)` and `offers (main_link)`.
  - The table `link_enrich_state(id INTEGER PRIMARY KEY CHECK (id = 1), last_run_at TEXT, pending INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0, blocked INTEGER NOT NULL DEFAULT 0)`.
- **Types** (`ports/links.py`), both frozen dataclasses:
  - `LinkRow`, mirroring the table;
  - `EnrichHeartbeat(last_run_at: datetime, pending: int, done: int, failed: int, blocked: int)`.
- **`LinkRepository` (Protocol):**
  - **`discover(limit: int = 50) -> int`.** It runs the `SELECT` (offers with `main_link IS NOT NULL`, `deleted = 0`, `GROUP BY main_link`, `NOT EXISTS` a row) **outside** any transaction, then `INSERT OR IGNORE`s the at most 50 rows in one short transaction. For the `main_link` values of non-deleted offers that have no row, it inserts `pending` rows with `url = main_link` unchanged and `offer_posted_at = MAX(posted_at)`, newest first. It returns the number of rows inserted.
  - **`next_due(now: datetime, paused_hosts: frozenset[str]) -> LinkRow | None`.** The predicate is `(status = 'pending' AND (next_try_at IS NULL OR next_try_at <= :now)) OR (status = 'blocked' AND next_try_at <= :now AND blocks < 2)`, plus `EXISTS (SELECT 1 FROM offers WHERE main_link = url AND deleted = 0)`. Rows are ordered by `offer_posted_at DESC`.
    - Paused hosts are filtered **in SQL**: `host NOT IN (...) AND (final_host IS NULL OR final_host NOT IN (...))`, so a paused big store never starves the others.
  - **`earliest_next_try(now: datetime, paused_hosts: frozenset[str]) -> datetime | None`** covers the same row set as `next_due` and ignores `done`, `failed` and paused rows.
  - **`known_product(store: str, product_id: str) -> tuple[str | None, str | None] | None`** returns `(title, image_url)` from a `done` row that has a title.
  - **`save(row: LinkRow, *, fix_store: bool) -> int`** runs one short transaction:
    - it updates the row;
    - if `fix_store` is set and the row has a store, it runs `UPDATE offers SET store = ? WHERE main_link = ? AND store IS NULL`, without touching `updated_at`;
    - it returns the number of offers fixed.
  - **`write_heartbeat(now: datetime) -> None`** and **`heartbeat() -> EnrichHeartbeat | None`.** This is the only heartbeat reader.
- **Offers upsert.** In `VALUES`, the store is `COALESCE(?, (SELECT pl.store FROM product_links pl WHERE pl.url = ?))`, with `main_link` bound twice; the extra bound value goes directly after the store parameter in the params tuple. `DO UPDATE` keeps `store = excluded.store`, which already carries the fixed store.
- **Join key.** `offers.main_link` is used exactly as stored, and every comparison is between equal strings.
- **Fake repository.** `InMemoryLinkRepository(offers: InMemoryOfferRepository)` implements `LinkRepository` over dicts. The fake offer repository takes an optional `links: InMemoryLinkRepository | None`; with it set, its `upsert` applies the same store COALESCE, and `save(fix_store=True)` rewrites the fake's offers. The survival tests run on both.

**Steps**
- [ ] **Failing contract tests**, run on the fake and on SQLite:
  - `discover`: ordering; idempotency; a URL whose offers are all deleted is skipped; a URL shared by 3 offers gives one row.
  - `next_due`: a `pending` row with a future `next_try_at` is not picked; `blocked` is picked only when `attempts < 2` and it is due; paused URL host and paused final host are both skipped; a row whose offers are all deleted is skipped.
  - `earliest_next_try`, `known_product`, and `save` with `fix_store` (a known store is never overwritten).
  - The heartbeat counts.
- [ ] **Failing survival tests.** Fix a store with `save(fix_store=True)`, then check it is still there after each of:
  - an upsert of the same message;
  - an edit;
  - `rebuild_offers`;
  - a blank redelivery;
  - `purge_text_before` (link rows and the fixed store stay).
- [ ] **Failing concurrency test.** Two threads, each with its own real `connect()` connection (WAL, `busy_timeout`): 200 offer upserts against 200 `save` calls. A third phase runs `discover` on 50k offers while the upserts continue. Assert no `OperationalError`, the longest single `save` and the longest upsert during `discover` each take under 0.5 s.
- [ ] **Migration test** on a populated DB.
- [ ] Run red, implement, run green, run the full checks.
- [ ] Commit `feat(offers): product_links table, link repository and store-preserving upsert`.

### Task 3: Fetcher port and httpx adapter
Spec §5.2.

**Files**
- Create:
  - `velkgram/offers/ports/fetcher.py`;
  - `velkgram/offers/adapters/http/__init__.py`;
  - `velkgram/offers/adapters/http/fetcher.py`.
- Modify: `pyproject.toml` (move `httpx` to the runtime dependencies) and `uv.lock` (`uv lock`).
- Test: `tests/offers/adapters/test_http_fetcher.py`.

**Interfaces (produces)**
- **`Fetcher` (Protocol)** has one method: `fetch(url: str, plan: FetchPlan, before_request: Callable[[str], None], budget_for: Callable[[str], int]) -> FetchOutcome`.
  - `before_request(url)` is called **before every request, on every hop**. The service throttles there and raises `HostPaused` when the host is paused; the fetcher then returns `status="paused"`.
  - `budget_for(final_url)` is evaluated when `plan.body_budget is None`.
  - There is no refetch.
- **`HttpxFetcher(client: httpx.Client | None = None, resolve_host: Callable[[str], list[str]] = _getaddrinfo, monotonic: Callable[[], float] = time.monotonic)`** implements spec §5.2:
  - `follow_redirects=False`, with a manual loop of at most 5 hops;
  - each `Location` is resolved with `urljoin`;
  - a set of visited URLs catches loops;
  - non-`http(s)` schemes, and hosts with any IP that is `not ip.is_global` (after unwrapping `ipv4_mapped`; this covers loopback, private, link-local, CGNAT and multicast), give `invalid`. Scheme and IP checks run **before** `before_request`, so an invalid hop never touches the throttle. The DNS-rebinding gap between this check and the connect is accepted;
  - headers: `Accept-Encoding: gzip, deflate`, a desktop User-Agent, and `Accept-Language: pt-BR`;
  - a 10 s timeout per request, and a 30 s chain deadline checked with `monotonic` inside the redirect and stream loops;
  - `first_hop_only` returns after the first `Location`;
  - the body is streamed only for `text/html`, stops at the budget after decoding, then the stream is closed. Decoding uses the charset from the header or `<meta charset>`, else UTF-8 with `errors="replace"`;
  - `answered_by` is the host that gave the last response;
  - httpx errors give `status="error"`;
  - the adapter does no logging.
- **`configure_fetch_logging() -> None`**, in the same adapter module, sets the `httpx` and `httpcore` loggers to WARNING.

**Steps**
- [ ] **Failing `httpx.MockTransport` tests.** A test fixture injects a fake `resolve_host` that returns a public IP, so no test hits DNS. Cover:
  - redirects: absolute, relative and protocol-relative;
  - 6 hops stops at 5;
  - a loop gives `invalid`;
  - an `intent://` URL gives `invalid`;
  - `127.0.0.1` and `10.0.0.5` give `invalid`;
  - `first_hop_only`;
  - `before_request` is called once per hop, with that hop's URL;
  - `HostPaused` gives `paused`;
  - `budget_for` is applied at the final host;
  - a non-HTML response has no body;
  - a multibyte character cut at the budget doesn't raise;
  - 403 and 429 come back with `answered_by`;
  - a timeout gives `error`;
  - the chain deadline, with a fake `monotonic`.
- [ ] **Failing logging test.** With `configure_fetch_logging()` on, `HttpxFetcher` over `MockTransport` and root at INFO, no captured record contains a `?tag=SECRET` query.
- [ ] **Failing real-socket test** on a stdlib `http.server` on localhost, with `protocol_version="HTTP/1.1"`. The server streams gzip chunks of pseudo-random text, calling `flush()` with a short sleep between chunks, and sets a `threading.Event` on `BrokenPipeError` or `ConnectionResetError`. Assert:
  - `fetch` returns within 2 s;
  - the body is at most the budget;
  - the event is set within 5 s.

  This test alone lets `resolve_host` return loopback.
- [ ] Move `httpx` to the runtime dependencies and run `uv lock`. Then run red, implement, run green, and run the full checks.
- [ ] Commit `feat(offers): httpx link fetcher with manual redirects, budgets and SSRF guard`.

### Task 4: Enrichment loop, CLI and compose service
Spec §4 (process), §5.1, §5.2 (throttle), §5.4, §5.7 (heartbeat write), §7.

**Files**
- Create: `velkgram/offers/services/enrich.py`.
- Modify:
  - `velkgram/apps/cli.py`:
    - add `cmd_enrich` and register `enrich` in `COMMANDS` and `build_parser`, with the flags `--once` and `--limit N`;
    - call `apply_migrations` first, as `cmd_rebuild_offers` does;
    - build the fetcher through a module-level `_make_fetcher()`;
    - call `configure_fetch_logging()`;
    - set a `threading.Event` on SIGTERM.
  - `velkgram/offers/__init__.py`: export `LinkEnricher` and `HostPaused`.
  - `compose.yaml`: an `enricher` service with:
    - `command: ["velkgram", "enrich"]`;
    - the same image, env and volume as the collector;
    - `restart: unless-stopped`;
    - `depends_on: migrate: condition: service_completed_successfully`;
    - `stop_grace_period: 45s`;
    - no healthcheck.
- Test: `tests/offers/services/test_enrich.py`, `tests/apps/test_cli_enrich.py`.

**Interfaces**
- **Consumes:**
  - from Task 1: `fetch_plan`, `budget_for`, `resolve`, `resolve_url_only`, `strip_query`, `host_of`;
  - from Task 2: `LinkRepository`;
  - from Task 3: `Fetcher` and `HostPaused`. `HostPaused` is defined in `ports/fetcher.py`.
- **Produces:** `LinkEnricher(links: LinkRepository, fetcher: Fetcher, clock: Clock, wait: Callable[[float], bool])`. `wait` defaults to the stop event's `wait`, so sleeps are interruptible.
  - **`step() -> bool`:**
    - runs `discover(50)` on the first step, again immediately while the previous call inserted a full batch of 50, and otherwise at most every 60 s;
    - then processes one due URL;
    - returns whether it processed a URL.
  - **`run(stop: threading.Event, limit: int | None = None, until_idle: bool = False) -> int`:**
    - loops until `stop` is set, or `limit` is reached, or — with `until_idle` — `step()` finds nothing due **and** the last `discover` returned 0;
    - when idle, waits `min(10 s, earliest_next_try − now)`;
    - writes the heartbeat after each URL, and at most once a minute while idle;
    - returns the number of URLs processed.
  - **Per-URL pipeline:**
    1. If `resolve_url_only(url)` gives `(store, id)` and `known_product` hits, copy the title and image, and save as `done` with no fetch.
    2. Otherwise call `fetcher.fetch(url, fetch_plan(url), before_request=self._throttle, budget_for=budget_for)`.
       - `_throttle(u)` first raises `HostPaused` if `host_of(u)` is paused.
       - It then waits until 2 s have passed since the last request to that host, and records the time.
    3. Run `resolve`.
    4. Map the status:
       - **`paused`:** the row is left unchanged (no attempt).
       - **2xx, 3xx left after 5 hops, `invalid`, 404, 410, any other 4xx except 403/429, and any response where `resolve` gives `kind = "product"` (including a 403 when the id came from the URL):** `done`.
       - **`error` or 5xx:** `attempts += 1`, then `next_try_at` = now + 5 min, 30 min, then 6 h. The 4th failed attempt sets `failed`.
       - **403 or 429 without an id:** `blocks += 1`, `next_try_at = now + 24 h`, status `blocked`; when `blocks` reaches 2 the status is `failed`. The host `outcome.answered_by` is paused for 30 min, in memory; it is forgotten on restart, which is accepted. `attempts` counts only errors.
    5. Save with `final_url = strip_query(outcome.final_url)`, and `fix_store=True` whenever a store is known.
  - **Logging:**
    - per URL: `log.info("link_enriched", extra={"host": host_of(url), "status": s, "kind": k})`;
    - exceptions are caught per URL and logged as `log.warning("link_enrich_failed", extra={"host": ..., "error": type(e).__name__})`, with no `exc_info`. Each one counts as an attempt.

**Steps**
- [ ] **Failing service tests.** Use a fake fetcher that calls `before_request` once per scripted hop, a fake clock and a recording `wait`. Cover:
  - newest first;
  - one fetch for a URL shared by many offers;
  - the throttle on intermediate hops (cutt.ly → tidd.ly → kabum, then tidd.ly again within 2 s, waits);
  - different hosts don't wait;
  - a 403 from the final host pauses that host;
  - a different host is still processed;
  - the Magalu 403 with an id from the URL gives `done`, with no pause;
  - the retry schedule, and `failed` after it;
  - `blocked` twice gives `failed`;
  - reuse skips the fetch;
  - the store fix applies only to unknown stores;
  - an exception for one URL is logged without its URL and counted;
  - discovery is bounded: with fewer than 50 new links, at most 2 `discover` calls over 100 steps within 60 s of fake time; with 120 new links, it runs back-to-back until a call returns fewer than 50;
  - `run(until_idle=True)` processes all 120 links before exiting;
  - 3xx after 5 hops, 404 and 410 give `done`; a paused host gives no attempt;
  - one error followed by a 403 still gets its single 24 h block retry (`blocks` separate from `attempts`);
  - `run(limit=3)`, `run(until_idle=True)` and `stop` all stop it;
  - the heartbeat is written while idle.
- [ ] **Failing redaction test.** URLs with `?tag=SECRET&ref=TOKEN`; no log record contains them, and the stored `final_url` has no `?`.
- [ ] **Failing CLI test.** Monkeypatch `cli._make_fetcher` to return the fake. `velkgram enrich --once --limit 2` on a temp DB processes 2 rows and exits 0. `--once` alone exits once it is idle. Calling the installed SIGTERM handler sets the stop event; the test restores the previous handler.
- [ ] Run red, implement, run green, then run the full checks and `docker compose config -q`.
- [ ] Commit `feat(offers): link enrichment loop, enrich command and compose service`.

### Task 5: Queries — images, feed collapse, other product
Spec §5.5, §5.6.

**Files**
- Modify:
  - `velkgram/offers/ports/queries.py`: new fields, all with defaults:
    - `OfferCard.image_url: str | None = None`;
    - `OfferCard.seen_channel_ids: tuple[int, ...] = ()`;
    - `MatchCard.other_product: bool = False`.
  - `velkgram/offers/adapters/sqlite/queries.py`.
  - `velkgram/offers/adapters/sqlite/repository.py` (`priced_points` and a new `dominant_key`).
  - `velkgram/offers/ports/repository.py`.
  - `tests/fakes/repositories.py` (`dominant_key` returns None in the fake; this is a SQLite-only rule, and it is documented).
- Test:
  - the offers queries tests;
  - `tests/offers/adapters/test_feed_perf.py` (not slow, extended);
  - `tests/offers/adapters/test_volume.py` (slow, with a rebuilt fixture).

**Interfaces (produces)**
- **FROM clauses.** `_page` and `_count_after` take a `from_clause: str` parameter.
  - The feed passes `offers o LEFT JOIN product_links pl ON pl.url = o.main_link`.
  - The coupons query passes `offers o`.
  - `matches_page` joins `pl` too.
  - `_card()` reads `image_url` only when the row has that column (`"image_url" in row.keys()`).
- **`image_url`** is set when `pl.kind = 'product' AND pl.product_id IS NOT NULL AND pl.image_url IS NOT NULL`.
- **`_NOT_SAME_PRODUCT`** is added in `_feed_where` only when the filter is fully empty: no `q`, no price bounds, no `stores`, no channel, and `priced_only` off. This amends spec §5.6. It hides `o` when there is an offer `x` such that:
  - `x` joins `px` on `px.url = x.main_link`, with `px.store = pl.store`, `px.product_id = pl.product_id` and `pl.product_id IS NOT NULL`;
  - `x.price_cents = o.price_cents` and `o.price_cents IS NOT NULL`;
  - `x.kind = 'product'` and `x.deleted = 0`;
  - **`x` is itself visible**: `_NOT_REPOST` becomes a function `_not_repost(outer: str, inner: str) -> str`; the feed uses `_not_repost("o", "r")` and the hiding offer uses `_not_repost("x", "xr")`;
  - `pl.product_id IS NOT NULL` comes first in the EXISTS, so unenriched rows short-circuit;
  - `(x.posted_at, x.channel_id, x.message_id) > (o.posted_at, o.channel_id, o.message_id)`;
  - `julianday(x.posted_at) - julianday(o.posted_at) <= 1.0`.
- **`seen_channel_ids`** is a `GROUP_CONCAT(DISTINCT h.channel_id)` over the visible offer and the offers it hides, with its own aliases `h`, `ph`, `hr`: same key and price, `(h.posted_at, h.channel_id, h.message_id) < (o.posted_at, o.channel_id, o.message_id)`, `julianday(o.posted_at) - julianday(h.posted_at) <= 1.0`, and `_not_repost("h", "hr")`. The result is parsed in Python. Chains longer than 24 h under-count the oldest offers; this is accepted. When collapse is off, it is `(o.channel_id,)`.
- **`count_feed_after`** uses the same FROM and WHERE, so it agrees with the list.
- **`OfferRepository.dominant_key(wish_id: int) -> tuple[str, str] | None`.** One SQL `GROUP BY pl.store, pl.product_id` over the wish's comparable priced matches gives the top 2 plus the keyed total, which go to `dominant_from_counts`.
  - `SqliteOfferQueries.product()` calls it **once** and passes the key into:
    - `priced_points(wish_id, dominant=key)`, which nulls the price of other-product matches and keeps `match_count`;
    - `_points(..., dominant=key)`;
    - `matches_page(..., dominant=key)`, which sets `other_product`.
  - `summaries(wish_ids)` calls `dominant_key` once per wish.
  - An "other product" match is one with a non-null key that differs from the dominant key, when a dominant key exists. The SQL, with a `LEFT JOIN product_links pl` in `priced_points`, `_points` and `summaries`, is `NOT (pl.store IS NOT NULL AND pl.product_id IS NOT NULL AND (pl.store <> ? OR pl.product_id <> ?))`.
  - The fake's `priced_points` accepts the `dominant` keyword and ignores it; `dominant_key` returns None in the fake. This is a documented exception to the every-method-on-both-fakes rule: the dominant rule is tested on SQLite only, in `tests/offers/adapters/test_queries_product.py`.

**Steps**
- [ ] **Failing query tests:**
  - **Images:** a product row, a not-product row, and a row with no image.
  - **Collapse:**
    - the same key and price within 24 h gives 1 card with 2 channel ids;
    - a different price gives no collapse;
    - 23 h 59 apart collapses, 24 h 01 apart doesn't, and both across midnight;
    - a NULL product id gives no collapse;
    - any filter turns collapse off;
    - **an original and its forward in another channel, with the same link and price, give exactly 1 card**;
    - three offers at the same instant don't duplicate or vanish;
    - paging with limit 1 across a collapsed group gives no repeats or gaps;
    - `count_feed_after` equals the list;
    - `coupons()` and `matches_page` still work.
  - **Other product:** a wish with keys `[A,A,A,B]`:
    - B is excluded from `_points`, the stats and the `summaries` sparkline and last price;
    - B is kept in `matches_page` with `other_product = True`;
    - `match_count` is unchanged;
    - `dominant_key` runs once per `product()`, checked by counting calls.

    A wish with `[A,B]` excludes nothing.
- [ ] **Add a non-slow EXPLAIN-shape test**: the collapse EXISTS uses `SEARCH … USING INDEX` and the feed has no `SCAN o`. Timing stays in the slow volume test.
- [ ] **Add a three-offers-at-one-instant test** that checks each card's chip count.
- [ ] **Rebuild the slow volume fixture.** About 5k distinct links over 50k offers, half of them enriched in `product_links`. Assert the first page, the 100th page and the filtered feed each take ≤ 150 ms. Extend the full-scan regex to `pl|px|xo`, and assert that the collapse EXISTS uses `SEARCH … USING INDEX`. Also time `product()`, `summaries()` for 20 wishes, and `matches_page` with keyed matches, each ≤ 150 ms, and assert the dominant `GROUP BY` plan has no `SCAN o`.
- [ ] Run red, implement, run green, run the full checks, and run `uv run pytest -q -m slow -k volume`.
- [ ] Commit `feat(offers): link images, same-product collapse and other-product exclusion in queries`.

### Task 6: Web — card image, chips, status line
Spec §5.5 (chip), §5.6 (markup), §5.7 (status line).

**Files**
- Modify:
  - `velkgram/offers/web/templates/_offer_card.html`;
  - `velkgram/offers/web/router.py` (map `seen_channel_ids` to names with the existing `names` dict);
  - the match row partial `velkgram/offers/web/templates/_product_matches.html`;
  - `velkgram/apps/web/static/velkgram.css`;
  - `velkgram/ingestion/web/router.py`: `build_router(..., enrich_status: Callable[[sqlite3.Connection], dict[str, object] | None] | None = None)`, called with the per-request connection like the existing `recent_failures` helper, so ingestion imports nothing from offers;
  - `velkgram/ingestion/web/templates/status.html`;
  - `velkgram/apps/web/main.py`: wire a helper that turns `LinkRepository.heartbeat()` into the plain dict `{"last_run_at", "pending", "blocked"}`.
- Test: the offers web tests, `tests/ingestion/web/test_status_router.py` and an apps web wiring test.

**Interfaces (produces)**
- **Card image.** `<img class="offer-thumb" src="{{ row.image_url }}" loading="lazy" decoding="async" referrerpolicy="no-referrer" alt="" width="96" height="96">`.
  - It renders only when `row.image_url` is set and `is_safe_https_url` passes again at render time.
  - The box has a fixed size, `object-fit: contain` and the surface background. A failed load shows an empty box, because no CSS-only detection exists; this amends spec §5.6. No inline JS.
- **Chips, in pt-BR:**
  - `visto em {n} canais` when n ≥ 2, with a `title` that lists the channel names;
  - `outro produto`, muted, with `title="Produto diferente do mais frequente deste desejo — fora do gráfico e das estatísticas"`.
- **Status line:**
  - `Enriquecimento de links: última execução há {X}; {pending} pendentes, {blocked} bloqueados`;
  - when there is no heartbeat: `Enriquecimento de links: ainda não executado`;
  - when the kwarg is not wired: no line at all.

**Steps**
- [ ] **Failing tests:**
  - the image renders only when it is set and https, with `lazy` and `no-referrer`;
  - both chips show their text and title;
  - the status line covers all three states;
  - the existing status-router tests still pass with no kwarg.
- [ ] Implement, run green, then run `uv run pytest tests/offers/web tests/ingestion/web tests/apps -q`. The implementer takes no screenshots and runs no audit; the controller's reviewer does both.
- [ ] Run the full checks, then commit `feat(web): link thumbnails, seen-in-channels and other-product chips, enricher status`.

## Execution (controller notes)
- **Order:** Task 1 first. Tasks 2 and 3 may run in parallel in separate worktrees, then Task 4, Task 5 and Task 6.
- **Briefs:** every brief carries the Global Constraints and the Review Focus.
- **Batch reviews**, each by one fresh reviewer with no prior context:
  - Tasks 1–3;
  - Task 4, plus a real-network smoke run on a DB copy: `velkgram enrich --once --limit 10`;
  - Tasks 5–6, with zoomed feed, product and status screenshots and both audits on port 8768.
- **Fix rounds:** Sonnet. A round with only LOW findings goes to Haiku.
- **Final:** one whole-branch reviewer.
- **Real-world check:** from spec §8, run by the controller on a DB copy.
