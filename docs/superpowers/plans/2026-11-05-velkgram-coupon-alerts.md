# Coupon Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** alert the owner when a coupon can lower the price of a wish, in both orders (coupon after offer, and offer after coupon).

**Architecture:**
- **Offers module:** detects coupon targets with a pure domain rule and publishes one `CouponMatchedWish` event per live coupon.
- **Alerting:** queues and sends coupon alerts with its own 3-day dedup.
- **Evaluator:** for the reverse order, it reads active coupons through an injected port, once per message, without breaking "alert first".

**Tech Stack:** Python 3.13, uv, SQLite, FastAPI + Jinja2 + HTMX, pytest, import-linter.

**Spec:** `docs/superpowers/specs/2026-11-05-velkgram-coupon-alerts-design.md`. Read the § cited by each task.

## Global Constraints
- **Language:** repo artifacts in English, user-facing text in pt-BR, and alert copy exactly as in spec §4.3.
- **Dependencies:** no new runtime dependencies.
- **Module boundaries:** `uv run lint-imports` must keep all 10 contracts. Alerting never imports offers internals and offers never imports alerting. Cross-module contact goes only through `velkgram/shared/events.py`, ports, and `offers/__init__.py` public API wired in `velkgram/apps/`.
- **Alert first:** nothing added may raise into `Evaluator._evaluate`, or delay persisting or sending a v1 alert. The v1 latency test must still pass.
- **TDD:** every behavior change is test-first.
- **Checks before every commit:** `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports && uv run pytest -q`.
- **Data and secrets:** never use `.env` or `data/velkgram.db` in tests. Never commit secrets or DB files. Never push.
- **Constants (spec §3/§4):**
  - `OVER_MAX_CEILING = 1.5`;
  - recent window `3 days` before the coupon's `posted_at`, up to now;
  - active coupon `24 h`;
  - live age limit `30 min`;
  - recent-offers cap `500`;
  - active-coupons limit `3`;
  - coupon lines `≤ 2`;
  - coupon dedup window `3 days`;
  - slow-port log threshold `50 ms`.
- **Skills:** every task loads `velkgram-architecture`, `velkgram-conventions`, `velkgram-testing` and `velkgram-task`.
- **Subagents:** Sonnet or Haiku only. An implementer never dispatches subagents. Implementers don't take or read screenshots; only reviewers do.

## Review Focus
1. **The coupon post is itself a term-matching message with a price** (e.g. "Cupom … acima de R$ 500"). It must never take the over-max path. It must not get a coupon line pointing at itself. Test owner: Task 5.
2. **A burst of targets.** One coupon matching 20 wishes must not delay a live v1 alert arriving right after. Test owner: Task 4 (queue), with an end-to-end latency case in Task 5.
3. **A restart in the middle of the 3-day window** must not re-send coupon alerts. Test owner: Task 3 (warm_cache over 3 days).
4. **`rebuild-offers` on the real DB** must emit zero events and zero alerts. Test owner: Task 2.
5. **A multi-tier coupon** (the real Mercado Livre post, 9 tiers) picks the applicable tier per offer price. The alert shows that tier's codes, and the `wcc:` key uses those codes. Test owner: Task 1 (rule), and Task 4 (key and text).

## Amendments from plan review 1 (binding, override the task text below)
- **A1 (Tasks 1, 2, 5). Message classification.** Replace `store_for_message` with a public offers function, `classify_message(m: MessageData) -> MessageClass`.
  - `MessageClass` is a frozen dataclass with `store: str | None` and `is_coupon_post: bool`.
  - It uses the same title, link and `coupon_deal` logic as `offer_from_message`. Refactor `offer_from_message` to call it, so the two can't drift.
  - Export it from `offers/__init__.py`.
  - In Task 5, the Evaluator takes `classify: Callable[[MessageData], tuple[str | None, bool]]`, which the apps wire. Its default returns `(None, False)`.
- **A2 (Task 1). The over-max ceiling lives in shared.**
  - Put `OVER_MAX_CEILING_NUM = 3` and `OVER_MAX_CEILING_DEN = 2` in `velkgram/shared/deals.py`, with `within_over_max(price_cents: int, max_cents: int) -> bool`, which returns `max_cents < price_cents and price_cents * 2 <= max_cents * 3`.
  - Use integer math only. Offers and alerting both use this helper.
  - The ≤-max case is checked separately, as `price <= max`.
- **A3 (Task 1). `applicable_tier` signature.** It takes primitives: `applicable_tier(tiers: Sequence[CouponTier], min_cents: int | None, discount: str, codes: tuple[str, ...], price_cents: int) -> AppliedTier | None`.
  - `AppliedTier` is a frozen dataclass with `discount`, `min_cents` and `codes`.
  - A tier with empty `codes` falls back to the coupon's `codes`.
  - A coupon with no codes at all is not a coupon offer (spec §3).
- **A4 (Task 1). Domain filtering.** `coupon_targets(coupon, wishes, offers, now)` keeps `now` and filters defensively:
  - same store;
  - posted within `[coupon.posted_at − 3 days, now]`;
  - priced, not deleted, not sold out;
  - `norm_text` not None.

  Task 1 tests every spec §8 domain case.
- **A5 (Task 2). Which offers can emit.**
  - Targets use `self._wishes.enabled()`, never `.all`. Add a test: a disabled wish gives no target.
  - **Repost:** an offer with `origin_channel_id` and `origin_message_id` both set is a repost (forwarded) and emits nothing. Add a test.
  - **Event fields:**
    - `coupon_posted_at = offer.posted_at` and `coupon_received_at = m.received_at`;
    - `store = offer.store` and `scope = offer.coupon_scope`;
    - `link = offer.redeem_link or offer.main_link`.
  - The outbox is cleared when `_handle` raises.
  - `active_coupons` applies the price filter in Python while iterating newest first, and stops at `limit`. The SQL has no LIMIT before the filter.
  - Add `recent_store_offers` to `tests/fakes/repositories.py`, and run the contract test on both the fake and SQLite.
- **A6 (Task 3). Restoring the dedup cache.** `warm_cache` calls `repo.list_since(now − 3 days)` once and remembers every key. `DedupCache.find` applies each rule's window. Keep retry's 30-min age as its own constant. Add no `list_coupon_since`.
  - The migration file must not contain BEGIN or COMMIT, because the migrator wraps it.
- **A7 (Tasks 3, 4). Pre-rendered text.**
  - Add `rendered: str | None = None` to `AlertMessage`. `format_alert` returns it verbatim when it is set.
  - `CouponAlerter` sends `AlertMessage(..., rendered=payload)`.
  - For retries, `Collector.build_message` returns that shape from `alert.payload` when `alert.kind == coupon`, without needing the stored message or the channel. `retry_failed.py` itself needs no change.
  - Add a test: a coupon alert is retried with the original message purged and is not expired.
- **A8 (Task 4). Collector drain.** `Collector.wait_idle` drains in this order: `offer_builder.drain()`, then `bus.drain()`, then `coupon_alerter.drain()`. Add a collector-assembly test that goes from a live coupon message to a sent coupon alert.
- **A9 (Task 5). Coupon lines.**
  - **Port call:** `_notify_and_finalize` calls the port with `price_cents=alert.price_cents`, `since = now − 24 h` and `exclude` set. No alerting-side re-filter. When the alert's price is None, there are no lines. Spec §4.2.3 is updated to match.
  - **Wish limits:** the Evaluator keeps `_wish_max: dict[int, int]` next to `_wish_names`, for the over-max suffix.
  - **Retries:** a retried over-max alert keeps its suffix. `build_message` reads the wish max from the wishlist.
  - **Port memo:** the once-per-message port memo lives outside the per-wish try block. A port error doesn't set `complete = False`.
  - **Tests:** replace the "slow port does not delay persisting" test with two tests: the notifier is called after a slow port returns, and `active_coupons_slow` is logged. Add a `FakeActiveCoupons` in `tests/fakes/`.
- **A10 (Task 6). Codes chip and latency stats.**
  - Codes for the chip come from the dedup key that starts with `wcc:`: take the text after its third `:`, then split on `,`.
  - `latency_samples` and the v1 latency p95 filter on `kind = 'offer'`. Add a test.
  - `daily_alert_counts` counts both kinds.
- **A11 (Task 4). Coupon with no discount text.** The first line omits ` — {discount}`. Add a format test.
- **A12 (Task 2). Review Focus 4 test.** Also cover `ingest_many` with a `source="live"` message younger than 30 min: it emits nothing.

---

### Task 1: Offers domain rule and the shared event
Spec §3, §4.1.2–3.

**Files:**
- Create `velkgram/offers/domain/coupon_targets.py`.
- Modify `velkgram/offers/domain/stores.py` (add `store_for_message`), `velkgram/shared/events.py`, `velkgram/offers/__init__.py` (export `store_for_message`).
- Test `tests/offers/domain/test_coupon_targets.py` and `tests/offers/domain/test_store_for_message.py`.

**Interfaces (produces):**
- `store_for_message(m: MessageData) -> str | None`. It uses the same `main_link` + `store_of` as `offer_from_message`. When the title starts with "cupom" (accents and case ignored), it falls back to `store_in_title`.
- `OVER_MAX_CEILING: float = 1.5`.
- `applicable_tier(coupon: Offer, price_cents: int) -> CouponTier | None`. A single-tier coupon is treated as one tier built from `coupon_discount`, `coupon_min_cents` and `coupons`. A `min_cents` of None counts as 0. The rule picks the highest min ≤ price; ties go to the first tier.
- `coupon_targets(coupon: Offer, wishes: Sequence[WishView], offers: Sequence[Offer]) -> tuple[CouponTargetData, ...]`. The input `offers` are already filtered by store, window, priced, not deleted and not sold out. For each wish, the rule keeps the offers where `matches_terms` passes, `applicable_tier` is not None, and `price ≤ max × OVER_MAX_CEILING`. It then takes the cheapest offer, ties going to the newest `posted_at`.
- In `shared/events.py`:
  - `@dataclass(frozen=True, slots=True) class CouponTargetData` with fields `wish_id: int`, `offer_channel_id: int`, `offer_message_id: int`, `offer_price_cents: int`, `over_max: bool`, `discount: str`, `min_cents: int | None` and `codes: tuple[str, ...]`;
  - `class CouponMatchedWish` with fields `coupon_channel_id: int`, `coupon_message_id: int`, `coupon_posted_at: datetime`, `coupon_received_at: datetime`, `store: str`, `scope: str | None`, `link: str | None` and `targets: tuple[CouponTargetData, ...]`;
  - add `CouponMatchedWish` to the `Event` union.

**Steps:**
- [ ] Write table tests, all built from the real posts in spec §8 (domain):
  - KaBuM "Selecionados" with no minimum: it applies at any price;
  - Shopee "R$ 10 OFF em R$ 40": it doesn't apply at R$ 39,99 and applies at R$ 40,00;
  - the ML 9-tier post: R$ 699 picks "R$ 90 OFF em R$ 699" with code `MOVEIS0511`, and R$ 150 picks the R$ 149 tier;
  - the ceiling: max R$ 1.500, R$ 2.250 is kept and R$ 2.250,01 is dropped;
  - two qualifying offers: the cheaper wins; on equal prices, the newer wins;
  - two wishes give two targets;
  - `over_max` is true only when price > max;
  - `store_for_message`: a tidd.ly-only coupon post titled "Cupom Kabum…" → `kabum`, amzn.to → `amazon`, no links → None.
- [ ] Run them and see them fail. Implement. Run them and see them pass. Run the full checks.
- [ ] Commit: `feat(offers): coupon target rule, store_for_message and CouponMatchedWish event`.

### Task 2: Offers queries and builder publishing
Spec §4.1.1–3, §4.2.1 (query side), §5 Offers.

**Files:**
- Modify:
  - `velkgram/offers/ports/repository.py`, adding `recent_store_offers`;
  - `velkgram/offers/ports/queries.py`, adding `active_coupons`;
  - the SQLite adapters of both;
  - `velkgram/offers/services/build_offer.py`;
  - `velkgram/offers/__init__.py`;
  - the collector wiring in `velkgram/apps/collector/collector.py`, which passes `bus.publish`.
- Test:
  - `tests/contracts/test_offer_repository.py`;
  - the offers queries tests (temp SQLite, the existing pattern);
  - `tests/offers/services/test_build_offer.py`.

**Interfaces:**
- Consumes everything Task 1 produces.
- Produces:
  - `OfferRepository.recent_store_offers(store: str, since: datetime, limit: int = 500) -> list[Offer]`. It returns `kind='product'` offers that are priced, not deleted and not sold out, with `posted_at >= since`, newest first.
  - `OfferQueries.active_coupons(store: str, since: datetime, price_cents: int | None, exclude: tuple[int, int] | None, limit: int = 3) -> list[ActiveCouponView]`. `ActiveCouponView` is a frozen dataclass in `ports/queries.py` with fields `channel_id`, `message_id`, `posted_at`, `discount: str`, `min_cents: int | None`, `codes: tuple[str, ...]`.
    - **Price filter:** when `price_cents` is set, it keeps only the coupons whose `applicable_tier` is not None. The view then carries the applicable tier's values.
    - **Exclusion:** `exclude=(channel_id, message_id)` drops that row.
    - **Plan:** `EXPLAIN QUERY PLAN` must use `idx_offers_store_kind_feed` (pin it in a test). Add no new index.
  - `OfferBuilder.__init__(…, publish: Callable[[Event], Awaitable[None]] | None = None)`.
    - **Outbox:** `ingest` appends a `CouponMatchedWish` to `self._outbox` only when all of these hold:
      - `source == MatchSource.live`;
      - `m.source == "live"`;
      - `now − m.date ≤ 30 min`;
      - the stored offer is a coupon offer (spec §3);
      - it is not a repost;
      - the targets are not empty.
    - **Publishing:** `run()` publishes and clears the outbox after each `_handle`, and so does `drain()`.
    - **Failures:** an exception in target building is logged as `coupon_targets_failed`, with the coupon ids, and swallowed.
    - **Never emits:** `ingest_many` never fills the outbox.
  - Public exports: `ActiveCouponView` and `store_for_message`.

**Steps:**
- [ ] Write the failing tests:
  - the contract for `recent_store_offers`: window bounds, the kind, priced/deleted/sold-out exclusions, and the limit;
  - `active_coupons`: the price filter, the exclusion, the limit, newest first, and the plan;
  - the builder:
    - a live coupon publishes one event with 2 targets;
    - the same coupon edited publishes again, since dedup is alerting's job;
    - backfill older than 30 min publishes nothing;
    - `ingest_many(source=retro)` and `rebuild_offers` publish nothing (Review Focus 4);
    - an exception in targets is logged and the offer is still stored.
- [ ] Implement, check that the tests pass, run the full checks, and commit `feat(offers): recent store offers, active coupons query and coupon events from live ingest`.

### Task 3: Alerting data and dedup
Spec §4.4, §4.5 (storage), §5 Alerting.

**Files:**
- Create `velkgram/alerting/migrations/002_coupon_alerts.sql`.
- Modify `velkgram/alerting/domain/models.py`, `velkgram/alerting/domain/dedup.py`, `velkgram/alerting/ports/repository.py`, the alerting SQLite repository and `velkgram/alerting/services/retry_failed.py` (`warm_cache`).
- Test `tests/alerting/domain/test_dedup.py`, `tests/contracts/test_alert_repository.py` and a migration test on a populated DB.

**Interfaces (produces):**
- `Alert` gains these fields, defaults last:
  - `kind: AlertKind = AlertKind.offer` (`StrEnum` with `offer` and `coupon`);
  - `over_max: bool = False`;
  - `offer_channel_id: int | None = None`;
  - `offer_message_id: int | None = None`;
  - `payload: str | None = None`.
- `SuppressionRule.wish_coupon`.
- Key builders:
  - `coupon_origin_key(wish_id, coupon_channel_id, coupon_message_id) -> str`, giving `wco:{w}:{c}:{m}`;
  - `coupon_content_key(wish_id, store, codes) -> str`, giving `wcc:{w}:{store}:{",".join(sorted(codes))}`.
  - Both map to `wish_coupon` in `rule_for_key`.
- `DedupCache(window: timedelta, rule_windows: Mapping[SuppressionRule, timedelta] = {})`. `find` and `prune` use the rule's own window.
- `warm_cache` loads 3 days for `wish_coupon` keys and the default window for the others.
- `AlertRepository.list_coupon_since(since: datetime) -> list[Alert]`, if `list_since` cannot be reused.

**Steps:**
- [ ] Write the failing tests:
  - the key formats;
  - `rule_for_key` on the new prefixes;
  - per-rule windows: a `wish_coupon` key still hits after 2 days and misses after 3 days and 1 second, while a `wp:` key misses after 31 min;
  - after a restart, `warm_cache` re-hits a coupon key alerted 2 days earlier (Review Focus 3);
  - the repository round-trips the new fields;
  - the migration on a DB with existing alerts and suppressions keeps the rows, accepts `wish_coupon` and still rejects an unknown rule.
- [ ] Implement:
  - the migration rebuilds `alert_suppressions` in one script: create the new table, copy the rows, drop the old one, rename it and recreate the index;
  - collector wiring: `DedupCache(_DEDUP_WINDOW, {SuppressionRule.wish_coupon: timedelta(days=3)})`.
- [ ] Check that the tests pass, run the full checks, and commit `feat(alerting): coupon alert fields, wish_coupon dedup rule and 3-day window`.

### Task 4: Coupon alert service
Spec §4.1.4, §4.3 (coupon alert text), §4.5.

**Files:**
- Create `velkgram/alerting/services/coupon_alerts.py`.
- Modify `velkgram/alerting/domain/format.py`, `velkgram/alerting/services/retry_failed.py` and `velkgram/apps/collector/collector.py` (subscribe, start the task, drain on shutdown).
- Test `tests/alerting/services/test_coupon_alerts.py` and `tests/alerting/domain/test_format.py`.

**Interfaces:**
- Consumes: from Task 1, `CouponMatchedWish` and `CouponTargetData`; from Task 3, `Alert` with its new fields, the key builders and `DedupCache`.
- Produces:
  - `format_coupon_alert(store: str, codes: tuple[str, ...], discount: str, min_cents: int | None, scope: str | None, wish_name: str, offer_price_cents: int, max_price_cents: int, over_max: bool, link: str) -> str`, which returns the text exactly as in spec §4.3, using `format_brl`;
  - `CouponAlerter(wishes: WishlistReader, repo: AlertRepository, cache: DedupCache, notifier: Notifier, clock: Clock, sleep=asyncio.sleep)`, with:
    - `async on_coupon(e: CouponMatchedWish) -> None`, which only enqueues;
    - `async run() -> None` and `async drain() -> None`.
  - **Processing per target:**
    1. Skip the target if the wish is not enabled.
    2. Build the keys; when the cache hits, add a suppression and stop.
    3. Otherwise add an `Alert` with:
       - `kind=coupon`;
       - `channel_id` and `message_id` set to the coupon's;
       - `price_cents` set to the offer price;
       - `over_max` and the `offer_*` ids;
       - `payload` set to the rendered text;
       - `delayed_minutes=None`;
       - the latencies from spec §4.1.4.
    4. Send through `send_with_retry` and update the status.
  - **Link:** when `e.link` is None, use `telegram_link(coupon_channel_id, coupon_message_id)`.
  - **Retry:** `retry_failed` resends `payload` as-is for `kind=coupon`.

**Steps:**
- [ ] Write the failing tests:
  - format tests for the plain, over-max, scope and multi-tier texts;
  - one event with 2 targets produces 2 alerts;
  - an edited coupon re-published within 3 days produces no second alert;
  - the same codes from another channel are suppressed by `wcc:`;
  - a disabled wish produces no alert;
  - `retry_failed` resends the payload;
  - the handler returns without sending: it returns before the notifier is called, with a fake that blocks (Review Focus 2).
- [ ] Implement, check that the tests pass, run the full checks, and commit `feat(alerting): coupon alerts queue, texts and retries`.

### Task 5: Offer after coupon in the evaluator
Spec §4.2, §4.3 (coupon line, above-max line).

**Files:**
- Create `velkgram/alerting/ports/active_coupons.py` and `velkgram/alerting/adapters/offers_api.py`.
- Modify `velkgram/alerting/domain/models.py` (`ActiveCoupon`, and `AlertMessage` gains `coupon_lines: tuple[str, ...] = ()` and `over_max_cents: int | None = None`), `velkgram/alerting/domain/format.py`, `velkgram/alerting/services/evaluate.py` and the collector wiring.
- Test `tests/alerting/services/test_evaluate_coupons.py`, `tests/alerting/domain/test_format.py` and the latency test file.

**Interfaces:**
- Consumes: `store_for_message` from Task 1, and `active_coupons` and `ActiveCouponView` from Task 2.
- Produces:
  - `ActiveCoupons(Protocol).for_store(store: str, since: datetime, price_cents: int | None, exclude: tuple[int, int] | None) -> list[ActiveCoupon]`, where `ActiveCoupon` carries the `ActiveCouponView` fields. The adapter wraps `OfferQueries.active_coupons` and `store_for_message`.
  - `Evaluator.__init__(…, coupons: ActiveCoupons | None = None, store_of: Callable[[MessageData], str | None] = lambda m: None)`.
  - **In `_evaluate`:**
    - Compute the store at most once per message, and call the port lazily, at most once per message, with `since = now − 24 h`, the message price and `exclude = (channel_id, message_id)`. The call happens only when some term-matched wish has `max < price ≤ max × 1.5` and the message is not a coupon post (its title starts with "cupom").
    - Wrap the call in try/except (log `active_coupons_failed`), and log `active_coupons_slow` above 50 ms.
    - Wishes in that band then go through `_decide` with `over_max=True`.
  - **In `_notify_and_finalize`:** call the port with `price_cents=None` and `exclude` set, filter to the coupons that apply to `alert.price_cents`, and build up to 2 coupon lines. On an error, send without the lines.

**Steps:**
- [ ] Write the failing tests:
  - an offer above max with an applicable active coupon alerts, with `over_max` set and the price line suffix;
  - above max without a coupon, or above the ceiling, gives no alert;
  - a port that raises gives v1 behavior in both call sites;
  - the coupon post itself ("Cupom … acima de R$ 500", matching terms) never calls the port on the over-max path and never gets a line pointing at itself (Review Focus 1);
  - a ≤ max alert gets at most 2 coupon lines, newest first;
  - the port is called at most once per message, with 3 matching wishes;
  - the latency test still passes;
  - a slow port in `_notify_and_finalize` does not delay persisting the alert;
  - 20 queued coupon events do not delay a live alert's persist (Review Focus 2, end to end with the real `MemoryBus`).
- [ ] Implement, check that the tests pass, run the full checks, and commit `feat(alerting): active coupons in v1 alerts and the above-max coupon rule`.

### Task 6: Alertas page chips
Spec §4.6.

**Files:**
- Modify `velkgram/alerting/ports/queries.py`, the alerting SQLite queries, `velkgram/alerting/web/templates/alerts.html`, `velkgram/apps/web/static/velkgram.css` (if needed) and `velkgram/reporting/adapters/alerting_api.py` (if it reads alert columns).
- Test `tests/alerting/web/test_alerts_page.py`.

**Interfaces:**
- Consumes the `Alert` fields from Task 3.
- Produces chips in pt-BR:
  - "cupom" with the codes. The codes come from the alert's `wcc:` dedup key: split on `:`, take the last part, then split on `,`. Store nothing new.
  - "acima do limite".
- Links use the Telegram post links.

**Steps:**
- [ ] Write the failing web tests: a coupon alert row shows the "cupom" chip and the codes; an over-max row shows "acima do limite"; an ordinary row shows neither.
- [ ] Implement, check that the tests pass, and run both layout audits. Both must print `violations by kind: {}`.
- [ ] Run the full checks and commit `feat(web): coupon and above-limit chips on the alerts page`.

## Execution (controller notes)
- Every task brief includes the Global Constraints and the Amendments relevant to that task.
- **Order:** Tasks 1 → 2 → 3 → 4 → 5 → 6, sequential.
- **Review batches:** each batch gets one context-free reviewer.
  - Tasks 1–2 (offers side);
  - Tasks 3–4 (alerting data and service);
  - Tasks 5–6 (evaluator and UI). This reviewer takes the zoomed screenshots of the Alertas page.
- **Fix rounds:** Sonnet. A round with only LOW findings goes to Haiku.
- **Final:** one whole-branch reviewer.
- **Real-DB check** after Task 6: on a scratch copy of the DB, run `rebuild-offers` and confirm 0 events and 0 alerts (Review Focus 4).
