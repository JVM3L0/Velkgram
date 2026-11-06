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
  - `velkgram/offers/domain/urls.py`
  - `velkgram/offers/domain/links.py`
  - `velkgram/offers/domain/dominant.py`
  - `tests/fixtures/links/*.html` (trimmed, scrubbed)
- Modify:
  - `velkgram/offers/web/format.py`: `safe_href` delegates to `is_safe_url`, and its behavior is unchanged.
  - `pyproject.toml`: add `httpx` to the two contracts.
- Test:
  - `tests/offers/domain/test_urls.py`
  - `tests/offers/domain/test_links.py`
  - `tests/offers/domain/test_dominant.py`

**Interfaces (produces)**
- `strip_query(url: str) -> str`: drops the query and the fragment.
- `is_safe_url(url: str | None) -> bool`: true only for http and https URLs. This is the current `safe_href` rule.
- `is_safe_https_url(url: str | None) -> bool`: https only.
- `FetchPlan`, a frozen dataclass: `follow: bool`, `first_hop_only: bool`, `body_budget: int`.
- `fetch_plan(url: str) -> FetchPlan`: chooses the plan from the original URL's host and path.
  - Amazon `/dp/` or `/gp/…` direct: no follow, 512 KB.
  - `s.click.aliexpress.com`: `first_hop_only`, 0.
  - `s.shopee.com.br`: follow, 0.
  - `meli.la`: follow, 512 KB.
  - Short-link hosts (`cutt.ly`, `tidd.ly`, `bit.ly`, `go.promotom.com.br`, `link.amazon`): follow, with the body budget decided after the final host. The service then calls `budget_for(final_url) -> int`.
  - Other hosts: follow, 64 KB.
- `budget_for(url: str) -> int`: the per-host budget from the constants table.
- `LinkInfo`, a frozen dataclass: `store: str | None`, `product_id: str | None`, `title: str | None`, `image_url: str | None`, `kind: Literal["product", "not_product", "unknown"]`.
- `FetchOutcome`, a frozen dataclass, plain data shared with the port: `final_url: str`, `hops: tuple[str, ...]`, `status: int | Literal["invalid", "error"]`, `content_type: str | None`, `body: str | None`.
- `resolve(original_url: str, outcome: FetchOutcome) -> LinkInfo`: the algorithm and the per-store table of spec §5.3.
  - **Product id normalization:** Amazon ASINs are uppercase. Mercado Livre ids are `MLB<digits>`, with no dash. Shopee ids are `<shopid>.<itemid>`.
  - **Blocked pages:** a body containing an Amazon captcha marker (`captcha` or `Robot Check` in `<title>`) is treated as blocked. Title and image are None, and the kind is `unknown`.
- `dominant_product(keys: Sequence[tuple[str, str] | None]) -> tuple[str, str] | None`.

**Steps**
- [ ] **Build the fixtures.** From the spike pages, keep each page's `<head>` and the JSON fragments the rules need (Amazon `hiRes`, Mercado Livre `item_id`). Replace every query string and token with `X`, and keep the files small (≤ 30 KB each).
- [ ] **Write the failing table tests** (`test_links.py`), with one row per spec §8 domain case:
  - Amazon ASIN, with `Amazon.com.br:` prefix and ` : Amazon.com.br…` suffix stripped, `hiRes`, and a captcha page;
  - KaBuM! og tags;
  - Mercado Livre social page with `item_id`, and title suffixes ` - R$ 16,14`, ` - R$ 1.299,00` and ` - R$ 1.299`;
  - a Mercado Livre social page without `item_id`, giving `not_product` with no image;
  - AliExpress `productId` in hop 1;
  - Shopee `/slug/123/456`, giving `123.456`;
  - Magalu `/magazinex/p/240162700/`, giving `240162700` with status 403 and kind `product`;
  - `link.amazon` campaign and `go.promotom` `/promocao/`, both giving `not_product`;
  - an unknown host with og tags, giving `unknown` with a title;
  - an unresolved cutt.ly interstitial (200, no hops), giving `unknown`;
  - an image with `http://` or `javascript:`, giving None;
  - a 250-char title, capped to 200.
- [ ] **Write the failing tests for the URL helpers and `fetch_plan`/`budget_for`** (`test_urls.py`), including a `safe_href` regression check.
- [ ] **Write the failing tests for `dominant_product`:**
  - `[A,A,A,B]` gives A;
  - `[A,A,B,B]` gives None (tie);
  - `[A,A]` gives None (fewer than 3);
  - `[A,A,B,None,None]` gives A (2 of 3 keyed is 66 %);
  - `[A,B,C]` gives None.
- [ ] Run the tests red. Implement. Run them green. Run the full checks.
- [ ] Commit: `feat(offers): link rules, URL helpers and dominant product`.

### Task 2: Data — migration, link repository, store-preserving upsert
Spec §5.1, §5.4 (writes), §6, §7 (locks).

**Files**
- Create:
  - `velkgram/offers/migrations/006_product_links.sql`
  - `velkgram/offers/ports/links.py`
  - `velkgram/offers/adapters/sqlite/links.py`
- Modify:
  - `velkgram/offers/adapters/sqlite/repository.py`: the `_UPSERT` store expression.
  - `tests/fakes/repositories.py`
- Test:
  - `tests/contracts/test_link_repository.py`
  - `tests/contracts/test_offer_repository.py`
  - `tests/offers/adapters/test_links_concurrency.py`
  - the migration test

**Interfaces (produces)**
- **Migration:**
  - creates `product_links` exactly as in spec §6;
  - creates the indexes `(status, next_try_at)`, `(store, product_id)` and `offers(main_link)`;
  - creates `link_enrich_state(id INTEGER PRIMARY KEY CHECK (id = 1), last_run_at TEXT, pending INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0, blocked INTEGER NOT NULL DEFAULT 0)`;
  - has no BEGIN/COMMIT.
- **`LinkRow`**, a frozen dataclass mirroring the table.
- **`LinkRepository` (Protocol):**
  - `discover(limit: int = 50) -> int`: inserts `pending` rows (`url = main_link`, unchanged) for the `main_link` values of non-deleted offers that have no row. The newest `MAX(posted_at)` comes first. Returns the number inserted.
  - `next_due(now: datetime, paused_hosts: frozenset[str]) -> LinkRow | None`: picks a `pending` row, or a `blocked`/`pending` row with `next_try_at <= now`. It skips rows whose URL host is in `paused_hosts` and orders by the newest linked offer.
  - `earliest_next_try() -> datetime | None`
  - `known_product(store: str, product_id: str) -> tuple[str | None, str | None] | None`: returns (title, image_url) from a `done` row with a title.
  - `save(row: LinkRow, *, fix_store: bool) -> int`: one short transaction. It updates the row. When `fix_store` is set and the row has a store, it also runs `UPDATE offers SET store = ? WHERE main_link = ? AND store IS NULL`. Returns the number of offers whose store was fixed.
  - `write_heartbeat(now: datetime) -> None`: recomputes the counts by status into `link_enrich_state`.
  - `heartbeat() -> EnrichHeartbeat | None`
- **The offers upsert** becomes `store = COALESCE(excluded.store, (SELECT pl.store FROM product_links pl WHERE pl.url = excluded.main_link))`. The insert path uses the same COALESCE.
- **The join key is `offers.main_link` exactly as stored.** `discover` writes `url = main_link` unchanged, so the store-fix `UPDATE`, the upsert lookup and every query join compare equal strings. There is no normalization on the key.

**Steps**
- [ ] **Write the failing contract tests** (fake and SQLite):
  - `discover`: ordering, idempotency, deleted-only links skipped, and one row for a URL shared by 3 offers;
  - `next_due`: `paused_hosts` and the `next_try_at` boundary;
  - `known_product`;
  - `save` with `fix_store`, where a known store is not overwritten;
  - heartbeat counts.
- [ ] **Write the failing tests that the fixed store survives.** First set the store through `save(fix_store=True)`, then check that it is still there after each of:
  - `upsert` of the same message;
  - an edit;
  - `rebuild_offers`;
  - a blank redelivery.
- [ ] **Write the failing concurrency test.** A second `sqlite3` connection (the real `connect()` with WAL and `busy_timeout`) runs 200 offer upserts while the first runs 200 `save` calls. There must be no `OperationalError`.
- [ ] **Write the failing migration test** on a populated DB: it applies cleanly and leaves existing offers untouched.
- [ ] Run red, implement, run green, run the full checks. Commit: `feat(offers): product_links table, link repository and store-preserving upsert`.

### Task 3: Fetcher port and httpx adapter
Spec §5.2.

**Files**
- Create:
  - `velkgram/offers/ports/fetcher.py`
  - `velkgram/offers/adapters/http/__init__.py`
  - `velkgram/offers/adapters/http/fetcher.py`
- Modify: `pyproject.toml` (move `httpx` to runtime) and `uv.lock` (`uv lock`).
- Test: `tests/offers/adapters/test_http_fetcher.py`, plus a stdlib-server test in the same file, marked as non-slow.

**Interfaces (produces)**
- `Fetcher (Protocol).fetch(url: str, plan: FetchPlan) -> FetchOutcome`. It is synchronous; the service is synchronous too. `FetchOutcome` and `FetchPlan` come from Task 1.
- `HttpxFetcher(client: httpx.Client | None = None, resolve_host: Callable[[str], list[str]] = <getaddrinfo IPs>)`. It implements spec §5.2:
  - `follow_redirects=False`, with a manual loop of at most 5 hops;
  - relative `Location` resolved with `urljoin`;
  - a visited set for loops;
  - non-`http(s)` schemes and private, loopback, link-local or unspecified IPs give `invalid`;
  - headers: `Accept-Encoding: gzip, deflate`, a desktop User-Agent and `Accept-Language: pt-BR`;
  - timeouts: 10 s per request and 30 s per chain;
  - `first_hop_only` returns after the first `Location`;
  - the body is streamed only for `text/html`. Reading stops at `plan.body_budget` bytes after decoding, and the stream is closed. Decoding uses the charset from the header or `<meta charset>`, falling back to UTF-8 with `errors="replace"`;
  - httpx errors give `status = "error"`.
- **No logging in the adapter.** It returns outcomes, and the service logs.

**Steps**
- [ ] **Write failing `httpx.MockTransport` tests:**
  - an absolute redirect, a relative redirect and a protocol-relative redirect;
  - 6 hops stops at 5;
  - a loop gives `invalid`;
  - `intent://` gives `invalid`;
  - a host resolving to `127.0.0.1` or `10.0.0.5` gives `invalid` (inject `resolve_host`);
  - `first_hop_only` returns after one hop, with that hop's `Location` in `hops`;
  - a non-HTML 200 has no body;
  - the budget holds with a multibyte character cut at the boundary, with no exception;
  - 403 and 429 come back as status codes;
  - a timeout gives `"error"`.
- [ ] **Write a failing real-socket test** with stdlib `http.server` on localhost. It serves a 2 MB gzip HTML page; the body is capped at 512 KB, and the server sees the connection closed before the full transfer. In this test only, `resolve_host` allows loopback.
- [ ] Move `httpx` to runtime and run `uv lock`. Then run red, implement, run green and run the full checks. Commit: `feat(offers): httpx link fetcher with manual redirects, budgets and SSRF guard`.

### Task 4: Enrichment loop, CLI and compose service
Spec §4 (process), §5.1, §5.2 (throttle, logging), §5.4, §5.7 (heartbeat write), §7.

**Files**
- Create: `velkgram/offers/services/enrich.py`.
- Modify:
  - `velkgram/apps/cli.py`: add an `enrich` command with `--once` and `--limit N`. It wires `HttpxFetcher`, the SQLite `LinkRepository` and the real clock, and sets the `httpx`/`httpcore` loggers to WARNING.
  - `velkgram/offers/__init__.py`: export `LinkEnricher`.
  - `compose.yaml`: add an `enricher` service with `command: ["velkgram", "enrich"]`, the same image, env and volume as the collector, `restart: unless-stopped`, `depends_on: migrate: condition: service_completed_successfully`, `stop_grace_period: 30s`, and no healthcheck.
- Test:
  - `tests/offers/services/test_enrich.py`
  - `tests/apps/test_cli_enrich.py`

**Interfaces**
- **Consumes:**
  - from Task 1: `fetch_plan`, `budget_for`, `resolve`, `strip_query`;
  - from Task 2: `LinkRepository`;
  - from Task 3: `Fetcher`.
- **Produces:** `LinkEnricher(links: LinkRepository, fetcher: Fetcher, clock: Clock, sleep: Callable[[float], None] = time.sleep)` with these methods:
  - `step() -> bool`: discovers new links and processes one due URL. Returns whether a URL was processed.
  - `run(stop: threading.Event | None = None, limit: int | None = None) -> int`: loops until `stop` is set or `limit` is reached. When nothing is due, it sleeps `min(10 s, earliest_next_try − now)`. It writes the heartbeat after each URL. SIGTERM in the CLI sets `stop`.
- **The pipeline for one URL:**
  1. Reuse: if `resolve` on the URL alone (an empty outcome with `final_url = url`) gives store and product id, and `known_product` hits, copy the title and image without fetching.
  2. Otherwise compute the plan, then throttle by host. The throttle is a per-host `last_request_at` map: sleep until 2 s have passed since the last request to that host, and apply it to the original host before fetching.
  3. Fetch. If the plan's budget depends on the final host, refetch only the final URL with `budget_for(final)`, applying the throttle again.
  4. Run `resolve`.
  5. Save: `final_url = strip_query(outcome.final_url)`. On any status where the store is known, call `save(fix_store=True)`.
- **Status mapping (spec §5.4):**
  - 2xx, `invalid`, `not_product` and `unknown` give `done`;
  - `error` and 5xx give retry rows with attempts + 1 and `next_try_at` set by the schedule; the 4th failed attempt gives `failed`;
  - 403 and 429 give `blocked`, with `next_try_at = now + 24 h`, a host pause of 30 min, and the attempts left unchanged.
- **Logging:** every per-URL log line has the form `log.info("link_enriched", extra={"host": host, "status": s, "kind": k})`. Exceptions are caught per URL and logged as `link_enrich_failed`, with only `host` and `error=type(e).__name__` and no `exc_info`. They count as an attempt.

**Steps**
- [ ] **Write failing service tests** with a fake fetcher, a fake clock and a recording sleep:
  - order: newest first;
  - one fetch for a URL shared by many offers;
  - throttle: two cutt.ly URLs in a row sleep 2 s, while cutt.ly then kabum does not;
  - a 403 on host A pauses A for 30 min, and a URL on host B is still processed;
  - the retry schedule (5 min, 30 min, 6 h, then `failed`);
  - `blocked` is retried after 24 h;
  - reuse skips the fetch;
  - the store fix happens only for unknown stores;
  - an exception for one URL is logged, counted, and the loop continues;
  - `run(limit=3)` stops;
  - `stop` set mid-run stops between URLs;
  - the heartbeat is written.
- [ ] **Write a failing redaction test:** run the loop over URLs with `?tag=SECRET&ref=TOKEN`, capturing all log records (root, `httpx`, `httpcore`). No record's message or args contains `SECRET` or `TOKEN`, and the stored `final_url` has no `?`.
- [ ] **Write a failing CLI test:** `velkgram enrich --once --limit 2` on a temp DB with a fake fetcher (injected through a module-level factory that the test monkeypatches) processes 2 rows and exits 0.
- [ ] Run red, implement, run green, run the full checks, and validate the compose file with `docker compose config -q`. Commit: `feat(offers): link enrichment loop, enrich command and compose service`.

### Task 5: Queries — images, feed collapse, other product, status read
Spec §5.5, §5.6, §5.7 (read).

**Files**
- Modify:
  - `velkgram/offers/ports/queries.py`: add `OfferCard.image_url: str | None`, `OfferCard.seen_channels: int`, `OfferCard.seen_channel_names: tuple[str, ...]` and `MatchCard.other_product: bool`.
  - `velkgram/offers/adapters/sqlite/queries.py`: the feed SELECT gets a LEFT JOIN on `product_links pl ON pl.url = o.main_link`.
  - `velkgram/offers/adapters/sqlite/repository.py`: `priced_points`.
  - `velkgram/offers/__init__.py`: export what the web needs.
- Test: the offers queries tests, the repository contract, and the volume test file (slow).

**Interfaces (produces)**
- **`image_url`** is set only when `pl.kind = 'product' AND pl.product_id IS NOT NULL AND pl.image_url IS NOT NULL`.
- **`_NOT_SAME_PRODUCT`**, an SQL predicate added in `_feed_where` only when `f.channel is None` (spec §5.6). It hides `o` when a newer offer `x` exists with:
  - the same `pl.store` and `pl.product_id`, both non-null;
  - the same non-null `price_cents`;
  - `kind = 'product'` and `deleted = 0`;
  - `x.posted_at > o.posted_at` and `x.posted_at <= datetime(o.posted_at, '+24 hours')`.
- **`seen_channels`** counts the distinct `channel_id` values among the visible offer and the offers it hides: those with the same key and price, posted at or before it and within 24 h. **`seen_channel_names`** is resolved through the existing channel-name injection in the router, not in SQL. When collapse is off, `seen_channels` is 1.
- **`count_feed_after`** uses the same WHERE, so it agrees with the list.
- **Dominant product:** `SqliteOfferQueries` runs `_dominant(wish_id) -> tuple[str, str] | None` once per wish. It loads the `(pl.store, pl.product_id)` keys of the wish's comparable priced matches and calls `dominant_product` from Task 1. `_points`, `product` stats, `summaries` and `SqliteOfferRepository.priced_points` then exclude the "other product" matches: a different non-null key while a dominant key exists. `priced_points` keeps `match_count` by turning their price into NULL, as it does for non-comparable matches. `matches_page` sets `MatchCard.other_product`.
- **`OfferQueries.enrich_status() -> EnrichHeartbeat | None`** reads `link_enrich_state`.

**Steps**
- [ ] **Write failing query tests:**
  - **images:** a product, a `not_product` and a missing image;
  - **collapse:**
    - same key and price within 24 h, giving one card with `seen_channels = 2`;
    - a different price gives no collapse;
    - 25 h apart gives no collapse;
    - a NULL product_id gives no collapse;
    - a channel filter turns collapse off;
    - a forwarded repost is counted once;
    - paging with limit 1 across a collapsed group gives no repeats and no gaps;
    - `count_feed_after` matches the list;
  - **other product:** a wish with `[A,A,A,B]` excludes B from `_points`, the stats and the `summaries` sparkline and last price, keeps it in `matches_page` with `other_product = True`, and leaves `match_count` unchanged. With `[A,B]`, nothing is excluded;
  - **`enrich_status`.**
- [ ] **Extend the slow volume test:** 50k offers with links, half of them enriched. The first feed page, the 100th page, and the filtered feed each take ≤ 150 ms. `EXPLAIN QUERY PLAN` shows that the join uses the `product_links` url index and the `(store, product_id)` index.
- [ ] Run red, implement, run green, run the full checks, and run `uv run pytest -q -m slow -k volume`. Commit: `feat(offers): link images, same-product collapse and other-product exclusion in queries`.

### Task 6: Web — card image, chips, status line
Spec §5.5 (chip), §5.6 (markup), §5.7 (status line).

**Files**
- Modify:
  - `velkgram/offers/web/templates/_offer_card.html`
  - `velkgram/offers/web/router.py`: view models and channel names for `seen_channel_names`.
  - `velkgram/offers/web/templates/_product_matches.html` (or the match row partial)
  - `velkgram/apps/web/static/velkgram.css`
  - `velkgram/ingestion/web/templates/status.html` and its router: the status line comes from an injected callable, because ingestion must not import offers internals. Follow the existing injection pattern for cross-module data on the status page; the apps layer wires `OfferQueries.enrich_status`.
- Test: the offers web tests and the status page test.

**Interfaces (produces)**
- **Card image:** `<img class="offer-thumb" src="{{ row.image_url }}" loading="lazy" decoding="async" referrerpolicy="no-referrer" alt="" width="96" height="96">`, with a fixed size, `object-fit: contain` on the surface background, and a CSS-only fallback that hides broken images (for example `img:not([src])`, plus a fixed box). There is no inline JS. The image is not rendered when `row.image_url` is None.
- **Chips, in pt-BR:**
  - `"visto em {n} canais"` when `n ≥ 2`, with a `title` listing the channel names;
  - `"outro produto"` on match rows, muted, with the title "Produto diferente do mais frequente deste desejo — fora do gráfico e das estatísticas".
- **Status line:** `"Enriquecimento de links: última execução há {X}; {pending} pendentes, {blocked} bloqueados"`. When there is no heartbeat, it reads `"Enriquecimento de links: ainda não executado"`.

**Steps**
- [ ] **Write failing web tests:**
  - the image appears only when `image_url` is set and has `loading="lazy"` and `referrerpolicy="no-referrer"`;
  - the chips show their text and title;
  - the status line covers both states.
- [ ] Implement, run the tests green, then run `uv run pytest tests/offers/web tests/ingestion/web -q`. The controller's reviewer runs the layout audit and takes the screenshots; the implementer does neither.
- [ ] Run the full checks. Commit: `feat(web): link thumbnails, seen-in-channels and other-product chips, enricher status`.

## Execution (controller notes)
- **Order:** Tasks 1 to 6, one after another. Tasks 1, 2 and 3 are independent of each other and may overlap in separate worktrees if time matters. Every brief carries the Global Constraints and the Review Focus.
- **Batch reviews**, each by one fresh reviewer with no prior context:
  - Tasks 1–2;
  - Tasks 3–4. This reviewer also runs a short real-network smoke on a DB copy: `velkgram enrich --once --limit 10`.
  - Tasks 5–6. This reviewer takes the zoomed feed, product and status screenshots and runs both audits on port 8768.
- **Fix rounds:** Sonnet. A round with only LOW findings goes to Haiku.
- **Final:** one whole-branch reviewer.
- **Real-world check (spec §8):** done by the controller on a DB copy, with at least 5 URLs per major host. The pass criteria are in the spec.
