# Coupon Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alert the owner when a coupon can lower the price of a wish. This works in both orders: the coupon after the offer, and the offer after the coupon.

**Architecture:**
- **Offers module:** a pure domain rule detects coupon targets, and offers publishes one `CouponMatchedWish` event per live coupon.
- **Alerting:** queues coupon alerts and sends them, with its own 3-day dedup.
- **Offer after coupon:** the v1 evaluator reads active coupons through an injected port, at most once per message, and keeps "alert first".

**Tech Stack:** Python 3.13, uv, SQLite, FastAPI, Jinja2, HTMX, pytest, import-linter.

**Spec:** `docs/superpowers/specs/2026-11-05-velkgram-coupon-alerts-design.md`. Read the sections each task cites. Where the spec and this plan differ in detail, the plan wins: it went through two context-free reviews after the spec.

## Global Constraints
- **Language:** repo artifacts are in English. User-facing text is in pt-BR, with the alert copy exactly as in spec §4.3. Money uses `format_brl`.
- **No new runtime dependencies.**
- **Module boundaries:** `uv run lint-imports` must keep all 10 contracts.
  - Alerting imports only the `velkgram.offers` root, the public API, and only in `alerting/adapters/`. Offers never imports alerting.
  - Shared plain data and pure helpers go in `velkgram/shared/`.
- **Alert first:**
  - nothing new may raise into `Evaluator._evaluate`;
  - nothing new may delay persisting a v1 alert;
  - a port error never sets `complete = False`;
  - the existing v1 latency test must still pass.
- **TDD:** every behavior change starts with a failing test.
- **Fakes:** every new port or repository method gets an in-memory fake in `tests/fakes/`, and the contract tests run on both the fake and SQLite.
- **Checks before each commit:** `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports && uv run pytest -q`.
- **Data safety:** never use `.env` or `data/velkgram.db` in tests. Never commit secrets or DB files. Never push.
- **Constants:**
  - over-max ceiling: `within_over_max(price, max)` in `shared/deals.py`, integer math only (`max < price and price * 2 <= max * 3`);
  - recent window: `[coupon.posted_at − 3 days, now]`;
  - active coupon: `24 h`;
  - live age limit: `30 min`;
  - recent-offers cap: `500`;
  - active-coupons limit: `3`;
  - coupon lines: at most `2`;
  - coupon dedup window: `3 days`;
  - slow-port log threshold: `50 ms`.
- **Skills:** every task loads `velkgram-architecture`, `velkgram-conventions`, `velkgram-testing` and `velkgram-task`.
- **Subagents:** Sonnet or Haiku only. Implementers never dispatch subagents and never take or read screenshots.

## Review Focus
1. **The coupon post is itself a v1 match.** A coupon post such as "Cupom … acima de R$ 500" matches terms and has a price. It must never take the over-max path, and it must never get coupon lines. Owner: Task 5.
2. **A burst of targets.** One coupon matching 20 wishes must not delay a live v1 alert that arrives right after it. Owners: Task 4 (the handler only enqueues) and Task 5 (an end-to-end test on the real `MemoryBus`).
3. **A restart inside the 3-day window** must not resend coupon alerts. Owner: Task 3, where `warm_cache` covers 3 days.
4. **`rebuild-offers` and `ingest_many`** emit zero events, even for a `source="live"` message younger than 30 min. Owner: Task 2.
5. **The real 9-tier Mercado Livre post** picks the applicable tier for each price, and both the text and the `wcc:` key use that tier's codes. Owners: Task 1 (the rule) and Task 4 (the key and the text).

---

### Task 1: Shared helpers, offers domain rule and the event
Spec §3, §4.1.2–3.

**Files:**
- Modify:
  - `velkgram/shared/deals.py` (add `within_over_max`);
  - `velkgram/shared/events.py`;
  - `velkgram/offers/domain/build.py` (add `classify_message`, and make `offer_from_message` use it);
  - `velkgram/offers/__init__.py` (export `classify_message` and `MessageClass`).
- Create: `velkgram/offers/domain/coupon_targets.py`.
- Test:
  - `tests/shared/test_deals.py`;
  - `tests/offers/domain/test_coupon_targets.py`;
  - `tests/offers/domain/test_classify_message.py`.

**Interfaces (produces):**
- `within_over_max(price_cents: int, max_cents: int) -> bool`. It returns `max_cents < price_cents and price_cents * 2 <= max_cents * 3`.
- `MessageClass`, a frozen dataclass with `store: str | None` and `is_coupon_post: bool`.
- `classify_message(m: MessageData) -> MessageClass`. It uses the same title, link, `store_of`, `store_in_title` and `coupon_deal` logic that `offer_from_message` uses today. `offer_from_message` calls it, so the two can't drift.
- `AppliedTier`, a frozen dataclass with `discount: str`, `min_cents: int | None` and `codes: tuple[str, ...]`.
- `applicable_tier(tiers: Sequence[CouponTier], min_cents: int | None, discount: str, codes: tuple[str, ...], price_cents: int) -> AppliedTier | None`.
  - With no tiers, it treats `(discount, min_cents, codes)` as the single tier.
  - A `min_cents` of None counts as 0. It picks the tier with the highest min ≤ price; ties go to the first tier.
  - A tier with empty `codes` falls back to the coupon-level `codes`.
- `coupon_targets(coupon: Offer, wishes: Sequence[WishView], offers: Sequence[Offer], now: datetime) -> tuple[CouponTargetData, ...]`.
  - It returns `()` unless the coupon is a coupon offer: `kind == 'coupon'`, a known store, at least one code, not deleted and not sold out.
  - It keeps only the offers that meet all of these:
    - the same store;
    - `posted_at` in `[coupon.posted_at − 3d, now]`;
    - `kind == 'product'`, priced, not deleted, not sold out;
    - `norm_text` is not None;
    - `matches_terms(wish, norm_text)` passes;
    - `applicable_tier` is not None;
    - `price <= max` or `within_over_max(price, max)`.
  - It returns one target per wish: the cheapest offer, ties going to the newest `posted_at`. `over_max` is true when `price > max`.
- In `shared/events.py`, `CouponTargetData` and `CouponMatchedWish` exactly as follows. Add `CouponMatchedWish` to the `Event` union.
  ```python
  @dataclass(frozen=True, slots=True)
  class CouponTargetData:
      wish_id: int
      offer_channel_id: int
      offer_message_id: int
      offer_price_cents: int
      over_max: bool
      discount: str
      min_cents: int | None
      codes: tuple[str, ...]


  @dataclass(frozen=True, slots=True)
  class CouponMatchedWish:
      coupon_channel_id: int
      coupon_message_id: int
      coupon_origin_channel_id: int | None  # forward origin, None when not forwarded
      coupon_origin_message_id: int | None
      coupon_posted_at: datetime
      coupon_received_at: datetime
      store: str
      scope: str | None
      link: str | None
      targets: tuple[CouponTargetData, ...]
  ```

**Steps:**
- [ ] Write the failing tests, all built from real posts:
  - `within_over_max`: with a max of 150000, a price of 225000 is True, 225001 is False and 150000 is False.
  - `classify_message` versus `offer_from_message` over every sample post: the store is the same, and `is_coupon_post` equals `kind == 'coupon'`.
  - `classify_message` stores: a tidd.ly-only post titled "Cupom Kabum…" gives `kabum`, an amzn.to link gives `amazon`, and a post with no links gives None.
  - `applicable_tier`:
    - a KaBuM! "Selecionados" coupon with no minimum applies at any price;
    - Shopee "R$ 10 OFF em R$ 40" does not apply at 3999 and applies at 4000;
    - on the Mercado Livre 9-tier post, 69900 picks "R$ 90 OFF" with code `MOVEIS0511`, and 15000 picks the R$ 149 tier;
    - a tier with no codes falls back to the coupon-level codes.
  - `coupon_targets`:
    - an offer older than 3 days before the coupon, and offers that are posted after the coupon but before now, are excluded and included respectively;
    - another store, an unknown store, and offers that are deleted, sold out, unpriced or have purged text are all excluded;
    - the ceiling;
    - the cheapest offer wins, and among equal prices the newest wins;
    - two wishes give two targets;
    - a coupon and an offer from different channels of the same store still pair;
    - a coupon with no codes gives `()`.
- [ ] Run the tests and watch them fail. Implement. Run them and watch them pass. Run the full checks.
- [ ] Commit: `feat(offers): coupon target rule, classify_message and CouponMatchedWish event`.

### Task 2: Offers queries and builder publishing
Spec §4.1.1–3, §4.2.1 (query side).

**Files:**
- Modify:
  - `velkgram/offers/ports/repository.py` and `velkgram/offers/ports/queries.py`;
  - their SQLite adapters;
  - `velkgram/offers/services/build_offer.py`;
  - `velkgram/offers/__init__.py`;
  - `tests/fakes/repositories.py`;
  - `velkgram/apps/collector/collector.py`, to pass `publish=bus.publish`.
- Test:
  - `tests/contracts/test_offer_repository.py`;
  - the offers queries tests (temp SQLite, the existing pattern);
  - `tests/offers/services/test_build_offer.py`.

**Interfaces:**
- **Consumes:** Task 1.
- **Produces:**
  - `OfferRepository.recent_store_offers(store: str, since: datetime, limit: int = 500) -> list[Offer]`.
    - It returns offers with `kind = 'product'` that are priced, not deleted and not sold out, with `posted_at >= since`, newest first.
    - It has both a fake and a SQLite implementation.
  - `ActiveCouponView`, a frozen dataclass in `offers/ports/queries.py` with these fields: `channel_id`, `message_id`, `posted_at`, `discount: str`, `min_cents: int | None` and `codes: tuple[str, ...]`.
  - `OfferQueries.active_coupons(store: str, since: datetime, price_cents: int | None, exclude: tuple[int, int] | None, limit: int = 3) -> list[ActiveCouponView]`.
    - SQL selects the coupons where `kind = 'coupon'`, the store matches, `posted_at >= since`, `deleted = 0` and `sold_out = 0`, newest first, with no LIMIT.
    - Python then iterates that result and builds the views:
      - drop the row equal to `exclude`;
      - drop coupons that have no codes;
      - if `price_cents` is set, keep only coupons with an `applicable_tier`, and fill the view from that tier;
      - if `price_cents` is None, fill the view from the coupon-level values;
      - stop at `limit`.
    - `EXPLAIN QUERY PLAN` uses `idx_offers_store_kind_feed`. Pin this in a test and add no index.
  - `OfferBuilder.__init__(…, publish: Callable[[Event], Awaitable[None]] | None = None)`.
    - **Outbox:** `ingest` appends a `CouponMatchedWish` to `self._outbox` only when all of these hold:
      - `self._publish` is not None;
      - `source == MatchSource.live`;
      - `m.source == "live"`;
      - `now − m.date <= 30 min`;
      - `coupon_targets(...)` is not empty.

      Targets use `self._wishes.enabled()` and `self._repo.recent_store_offers(store, coupon.posted_at − 3d)`. Event fields:
      - `coupon_origin_*`: the forward ids, when both are set;
      - `coupon_posted_at = offer.posted_at` and `coupon_received_at = m.received_at`;
      - `store = offer.store` and `scope = offer.coupon_scope`;
      - `link = offer.redeem_link or offer.main_link`.
    - **Forwarded coupons emit too.** Alerting dedups them by origin.
    - **Errors:** an exception while building targets is logged as `coupon_targets_failed` with the coupon ids and swallowed. The offer stays stored, and `_handle` clears the outbox on any exception.
    - **Publishing:** after each `_handle`, `run()` and `drain()` publish the outbox and clear it. They wrap each publish in try/except and log `coupon_event_publish_failed`, so the worker loop never dies.
    - **`ingest_many` never fills the outbox.**
  - Export `ActiveCouponView` from `offers/__init__.py`.

**Steps:**
- [ ] Write the failing tests:
  - **Contract for `recent_store_offers`:** window bounds, kind, the priced, deleted and sold-out exclusions, and the limit. Run it on the fake and on SQLite.
  - **`active_coupons`:**
    - the price filter, including the Mercado Livre tier chosen for a price;
    - the exclusion;
    - the limit is applied after the filter: 4 newer coupons that don't apply and 1 older one that does return the older one;
    - newest first;
    - codeless, sold-out and deleted coupons are dropped;
    - the query plan.
  - **Builder:**
    - a live coupon publishes 1 event with 2 targets;
    - a forwarded live coupon publishes, and the event carries the origin;
    - an edit re-publishes;
    - a disabled wish gives no target;
    - backfill older than 30 min, `ingest_many(source=retro)`, `rebuild_offers` and `ingest_many` with a `source="live"` message younger than 30 min publish nothing;
    - a builder with `publish=None` never grows its outbox;
    - when target building raises, the error is logged and the offer is still stored;
    - when publish raises, the error is logged and the worker keeps running.
- [ ] Implement until the tests pass, run the full checks, and commit `feat(offers): recent store offers, active coupons query and coupon events from live ingest`.

### Task 3: Alerting data and dedup
Spec §4.4, §5 Alerting.

**Files:**
- Create: `velkgram/alerting/migrations/002_coupon_alerts.sql`.
- Modify:
  - `velkgram/alerting/domain/models.py` and `velkgram/alerting/domain/dedup.py`;
  - `velkgram/alerting/ports/repository.py` and the alerting SQLite repository;
  - `tests/fakes/repositories.py`;
  - `velkgram/alerting/services/retry_failed.py` (`warm_cache`);
  - the `DedupCache` construction in `velkgram/apps/collector/collector.py`;
  - `velkgram/reporting/adapters/alerting_api.py`, wherever it maps `SuppressionRule`.
- Test: `tests/alerting/domain/test_dedup.py`, `tests/contracts/test_alert_repository.py`, and a migration test on a populated DB.

**Interfaces (produces):**
- `AlertKind(StrEnum)`, with the values `offer` and `coupon`.
- `Alert` gains these fields, at the end and with defaults:
  - `kind: AlertKind = AlertKind.offer`;
  - `over_max: bool = False`;
  - `offer_channel_id: int | None = None`;
  - `offer_message_id: int | None = None`;
  - `payload: str | None = None`.
- `SuppressionRule.wish_coupon`.
- `coupon_origin_key(wish_id: int, channel_id: int, message_id: int, fwd_channel_id: int | None, fwd_message_id: int | None) -> str` produces `wco:{wish}:{c}:{m}`. It uses the forward ids when both are set, following the same rule as `origin_key`.
- `coupon_content_key(wish_id: int, store: str, codes: tuple[str, ...]) -> str` produces `wcc:{wish}:{store}:{",".join(sorted(codes))}`.
- Both prefixes map to `wish_coupon` in `rule_for_key`.
- `DedupCache(window: timedelta, rule_windows: Mapping[SuppressionRule, timedelta] | None = None)`. `find` and `prune` use each rule's own window.
- `warm_cache` calls `repo.list_since(now − 3 days)` once and remembers every key; `find` enforces each window. The 30-min retry age stays its own constant.
- `has_alert_for_message` counts only `kind = 'offer'`, in SQLite and in the fake.
- The migration:
  - adds `kind TEXT NOT NULL DEFAULT 'offer' CHECK (kind IN ('offer','coupon'))`;
  - adds `over_max INTEGER NOT NULL DEFAULT 0`;
  - adds `offer_channel_id INTEGER`, `offer_message_id INTEGER` and `payload TEXT`;
  - rebuilds `alert_suppressions` with `wish_coupon` in its CHECK: create the new table, copy the rows, drop the old table, rename, and recreate the index.

  The migration file contains no BEGIN or COMMIT, because the migrator wraps it.

**Steps:**
- [ ] Write the failing tests:
  - the key formats, including a forwarded origin;
  - `rule_for_key` on `wco:` and `wcc:`;
  - per-rule windows: `wish_coupon` hits at 2 days and misses at 3 days plus 1 s, while `wp:` misses at 31 min;
  - after a restart, `warm_cache` hits a coupon key that was alerted 2 days ago;
  - the repository round-trips the new fields;
  - `has_alert_for_message` ignores coupon alerts;
  - the migration on a DB with existing alerts and suppressions: rows are kept, `wish_coupon` is accepted, and an unknown rule is still rejected;
  - the reporting suppression stats show `wish_coupon` with its own label "cupom".
- [ ] Implement until the tests pass, run the full checks, and commit `feat(alerting): coupon alert fields, wish_coupon dedup rule and 3-day window`.

### Task 4: Coupon alert service and collector lifecycle
Spec §4.1.4, §4.3 (coupon alert), §4.5.

**Files:**
- Create: `velkgram/alerting/services/coupon_alerts.py`.
- Modify:
  - `velkgram/alerting/domain/models.py` (`AlertMessage.rendered`);
  - `velkgram/alerting/domain/format.py`;
  - `velkgram/apps/collector/collector.py` (subscribe, start and stop the task, `wait_idle`, `build_message`);
  - `velkgram/apps/collector/main.py` (stop on shutdown);
  - `tests/apps/conftest.py` (stop the new worker).
- Test:
  - `tests/alerting/services/test_coupon_alerts.py`;
  - `tests/alerting/domain/test_format.py`;
  - `tests/apps/test_collector_assembly.py`.

**Interfaces:**
- **Consumes:** from Task 1, `CouponMatchedWish` and `CouponTargetData`; from Task 3, `Alert`, the key builders and `DedupCache`.
- **Produces:**
  - `AlertMessage.rendered: str | None = None`. When it is set, `format_alert` returns it verbatim.
  - `format_coupon_alert(store: str, codes: tuple[str, ...], discount: str, min_cents: int | None, scope: str | None, wish_name: str, offer_price_cents: int, max_price_cents: int, over_max: bool, link: str) -> str`. It produces the text in spec §4.3. When `discount` is empty, the first line omits ` — {discount}`.
  - `CouponAlerter(wishes: WishlistReader, repo: AlertRepository, cache: DedupCache, notifier: Notifier, clock: Clock, sleep=asyncio.sleep)` with these methods:
    - `async on_coupon(e: CouponMatchedWish) -> None` only enqueues;
    - `async run() -> None`;
    - `async drain() -> None`;
    - `async stop() -> None`.
  - **Processing each target:**
    1. Skip the target if the wish is not enabled.
    2. Build the keys: `wco` from the coupon ids and its origin, and `wcc` from `e.store` and the target's codes.
    3. On a cache hit, add a suppression with rule `wish_coupon` and stop.
    4. Otherwise add an `Alert` with:
       - `kind=coupon`;
       - `channel_id`/`message_id` from the coupon, and `price_cents` from the offer price;
       - `over_max` and the `offer_*` ids;
       - `payload` set to the rendered text;
       - `delayed_minutes=None`;
       - `latency_telegram_ms = coupon_received_at − coupon_posted_at` and `latency_internal_ms` = processing time.
    5. Remember the keys, then `send_with_retry(AlertMessage(..., rendered=payload))` and update the status.
  - **Link:** when `e.link` is None, use `telegram_link(coupon_channel_id, coupon_message_id)`.
  - **Retry:** `Collector.build_message` returns `AlertMessage(rendered=alert.payload, …)` for `kind == coupon`, without reading the stored message or the channel. `retry_failed.py` is unchanged.
  - **Collector lifecycle:**
    - `start()` creates the alerter task, then subscribes `CouponMatchedWish`.
    - `stop_offer_worker()` also stops the alerter, and so do `main.py` and `tests/apps/conftest.py`.
    - `wait_idle()` loops until all queues are empty, repeating: `bus.drain()`, `offer_builder.drain()`, `bus.drain()`, `coupon_alerter.drain()`, `evaluator.wait_idle()`, `bus.drain()`.

**Steps:**
- [ ] Write the failing tests:
  - **Format:**
    - plain;
    - over-max;
    - with a scope;
    - with no discount;
    - the Mercado Livre tier codes.
  - **Alerts:**
    - 1 event with 2 targets gives 2 alerts;
    - an edited coupon republished within 3 days gives no second alert;
    - the same codes from another channel are suppressed by `wcc:`;
    - a forward of an alerted coupon is suppressed by `wco:` through its origin;
    - a disabled wish gives no alert.
  - **Queue:** `on_coupon` returns before the notifier is called, using a notifier fake that blocks.
  - **Retry:** a coupon alert whose message was purged is retried and sent from its payload, and is not expired.
  - **Collector assembly:**
    - a live coupon message after a matching offer goes through `bus.drain()` and `wait_idle()` and produces 1 sent coupon alert;
    - stopping the collector leaves no pending tasks.
  - **Accepted, test as is:** when a ≤-max v1 alert already went out with a coupon line, a later coupon edit within 30 min can still produce one coupon alert for the same pair. The test pins exactly one.
- [ ] Implement until the tests pass, run the full checks, and commit `feat(alerting): coupon alerts queue, texts, retries and collector lifecycle`.

### Task 5: Offer after coupon in the evaluator
Spec §4.2, §4.3 (coupon line, above-max suffix).

**Files:**
- Create: `velkgram/alerting/ports/active_coupons.py`, `velkgram/alerting/adapters/offers_api.py` and `tests/fakes/active_coupons.py`.
- Modify:
  - `velkgram/alerting/domain/models.py`: add `ActiveCoupon`, plus `AlertMessage.coupon_lines: tuple[str, ...] = ()` and `over_max_cents: int | None = None`.
  - `velkgram/alerting/domain/format.py`.
  - `velkgram/alerting/services/evaluate.py`.
  - The collector wiring and `build_message`.
- Test: `tests/alerting/services/test_evaluate_coupons.py`, `tests/alerting/domain/test_format.py`, and the latency test file.

**Interfaces:**
- **Consumes:**
  - `classify_message` and `MessageClass` (Task 1);
  - `OfferQueries.active_coupons` and `ActiveCouponView` (Task 2);
  - the `Alert` fields (Task 3).
- **Produces:**
  - `ActiveCoupon`: a separate frozen dataclass in the alerting domain, with the fields `channel_id`, `message_id`, `posted_at`, `discount`, `min_cents` and `codes`. The adapter maps it from `ActiveCouponView` field by field.
  - `ActiveCoupons(Protocol).for_store(store: str, since: datetime, price_cents: int | None, exclude: tuple[int, int] | None) -> list[ActiveCoupon]`. Its adapter, `OffersActiveCoupons(queries: OfferQueries)`, lives in `alerting/adapters/offers_api.py`.
  - `Evaluator.__init__(…, coupons: ActiveCoupons | None = None, classify: Callable[[MessageData], tuple[str | None, bool]] = lambda m: (None, False))`. The apps wire `classify` as `lambda m: (c.store, c.is_coupon_post)` over `classify_message`.
  - **`_evaluate`:**
    - Classify the message once.
    - For wishes whose terms match and whose price satisfies `within_over_max(price, max)`, the message is a candidate. A coupon post never is.
    - For a candidate, call the port lazily, at most once per message, outside the per-wish try. Use `since = now − 24 h`, the message price, and `exclude = (channel_id, message_id)`.
      - A non-empty result sends those wishes through `_decide` with `over_max=True`.
      - An error logs `active_coupons_failed` and leaves `complete` unchanged.
      - A call above 50 ms logs `active_coupons_slow`.
  - **`_notify_and_finalize`:**
    - If the message is not a coupon post and `alert.price_cents` is not None, call the port once with `price_cents = alert.price_cents`, `since = now − 24 h` and `exclude` set.
    - Build at most 2 coupon lines, newest first.
    - Memoize the result per `(channel_id, message_id, price)` in a small dict that lives as long as the evaluator, so the tasks of several wishes for one message share one lookup.
    - On a port error, send without the lines.
    - `over_max_cents` comes from `_wish_max: dict[int, int]`, which is filled next to `_wish_names`.
  - **`build_message`:** on a retry of an over-max alert, it keeps the suffix, using the wish max from the wishlist. Coupon lines are not re-fetched on retry.

**Steps:**
- [ ] Write the failing tests.
  - **Format:**
    - a coupon line with 1 code and with 2 codes;
    - a coupon line with no discount;
    - the over-max price suffix.
  - **Over-max path:**
    - above max with an applicable active coupon: an alert is sent, `over_max` is set, and the text has the suffix;
    - above max with no coupon, or above the ceiling: no alert;
    - the port raises at either call site: the v1 behavior holds and `complete` stays true;
    - a coupon post that matches terms never calls the port and gets no lines (Review Focus 1).
  - **Coupon lines:**
    - an alert at or below max gets at most 2 lines, newest first;
    - one message with 3 matching wishes calls the port once in `_evaluate` and once in total in `_notify_and_finalize`.
  - **Timing:**
    - with a slow fake port, the notifier is called only after the port returns, and `active_coupons_slow` is logged;
    - the existing latency test still passes;
    - 20 queued `CouponMatchedWish` events on the real `MemoryBus` do not delay persisting a live alert (Review Focus 2).
- [ ] Implement until the tests pass, run the full checks, and commit `feat(alerting): active coupons in v1 alerts and the above-max coupon rule`.

### Task 6: Alertas page chips and stats
Spec §4.6.

**Files:**
- Modify:
  - `velkgram/alerting/ports/queries.py` and the alerting SQLite queries;
  - `velkgram/alerting/web/templates/alerts.html`;
  - `velkgram/alerting/__init__.py`, to export `AlertKind`;
  - `velkgram/apps/web/static/velkgram.css`, only if needed.
- Test: extend `tests/alerting/web/test_alert_router.py` and the alerting queries tests.

**Interfaces:**
- **Consumes:** the `Alert` fields from Task 3.
- **Produces:**
  - **Chips, in pt-BR:**
    - "cupom", followed by the codes. The codes are taken from the dedup key that starts with `wcc:`: take the text after its third `:` and split it on `,`.
    - "acima do limite".
  - **Links:** the Telegram post links.
  - **Stats:**
    - `latency_samples`, and the v1 p95 that comes from it, filter on `kind = 'offer'`;
    - `daily_alert_counts` counts both kinds.

**Steps:**
- [ ] Write the failing tests:
  - a coupon row shows the "cupom" chip and its codes;
  - an over-max row shows "acima do limite";
  - an ordinary row shows neither;
  - `latency_samples` excludes coupon alerts.
- [ ] Implement until the tests pass, then run `uv run pytest tests/apps/web tests/alerting -q`. The controller runs the layout audit and its reviewer takes screenshots. The implementer does neither.
- [ ] Run the full checks, then commit `feat(web): coupon and above-limit chips on the alerts page`.

## Execution (controller notes)
- **Order:** Tasks 1, 2, 3, 4, 5, 6, one after another. Every brief carries the Global Constraints.
- **Reviews:** one context-free reviewer per batch:
  - Tasks 1–2, the offers side;
  - Tasks 3–4, alerting data and service;
  - Tasks 5–6, evaluator and UI. Only this reviewer takes screenshots of the Alertas page and runs the scratchpad `audit.js`.
- **Fix rounds:** Sonnet. A round with only LOW findings goes to Haiku.
- **Final:** one whole-branch reviewer.
- **Real-DB check after Task 6:** run `migrate` and `rebuild-offers` on a scratch copy of the DB, and confirm 0 events and 0 new alerts (Review Focus 4).
