# Velkgram: coupon alerts for wishes (design)

- **Status:** approved in conversation on 2026-11-05. Revised after a context-free review. Awaiting the owner's review of this written spec.
- **Builds on:** `2026-11-04-velkgram-design.md` (v1 alerting: latency, dedup, "alert first") and `2026-11-04-velkgram-v0.2.0-design.md` (offers, coupons).
- **Order:** feature 1 of the sequence: coupon alerts, then the phone notifier, then the JSON API, then link scraping.

## 1. Purpose
Coupon posts usually apply to many products. Example: "Cupom KaBuM! 10% OFF acima de R$ 500: KORUJAO". Today the owner only sees them by browsing the Cupons tab. The goal is an alert whenever a coupon can lower the price of something on the wishlist.

### Owner facts and decisions
- The price in a post is always the final price. Never estimate or compute a price after the coupon.
- **Coupon after offer:**
  - A new coupon alerts for a wish when a product offer from the same store, posted recently, matches the wish's terms and has a price the coupon applies to.
  - The wish's "Alerta até" does **not** filter. An offer above the limit still counts, and the alert says so.
- **Offer after coupon:** a coupon from the offer's store counts as active when it was posted in the last 24 h.
  - An alert that would fire anyway gets a coupon line.
  - An offer above "Alerta até" also alerts, when an active coupon applies to its price.
    - This is the only change to the v1 alert decision.
    - It is bounded by the ceiling in §3.

## 2. Non-goals
- Computing the price after the coupon, or checking that a "Selecionados" coupon really covers the product.
- Linking coupons to wishes by anything other than the store, plus the offer's terms match.
- Changes to v1 term matching, price extraction, latency targets or dedup rules, beyond what §4.2 states.
- Coupon expiry parsing. "Active" means posted in the last 24 h, not sold out and not deleted.

## 3. Definitions
- **Store of a message:** `offers.classify_message(m)` (returns the store and whether the post is a coupon post) is a new public, pure function. It uses the same `main_link` + `store_of` that `offer_from_message` uses. For posts whose title starts with "cupom", it falls back to `store_in_title`. It returns None when the store is unknown.
- **Coupon offer:** an offer with `kind = 'coupon'`, a known store and at least one code, that is neither deleted nor sold out.
- **Applies to a price:**
  - **Single-tier coupon:** it applies when `coupon_min_cents` is None or ≤ the price.
  - **Multi-tier coupon:** it applies when some tier's `min_cents` is ≤ the price, where None counts as 0.
  - **Applicable tier:** the tier with the highest `min_cents` (None = 0) that is ≤ the price. Ties go to the first tier in post order.
  - **What the alert shows:** the discount, minimum and codes of the applicable tier. A single-tier coupon behaves as one tier.
- **Over-max ceiling:** `OVER_MAX_CEILING = 1.5`, a domain constant. An offer above "Alerta até" counts only if its price ≤ `max_price_cents × 1.5`. Without this, any no-minimum coupon (for example "10% OFF em Selecionados") would turn every term-matching offer of that store into an alert for 24 h, at any price.
- **Recent window:** product offers with `posted_at` in `[coupon.posted_at − 3 days, now]`. Offers posted just after the coupon but stored before it are still found.

## 4. Behavior

### 4.1 Coupon after offer (offers → alerting)

1. **Trigger.** `OfferBuilder.ingest` is the single live and edit path.
   - When it stores a coupon offer with `MessageData.source == "live"` and `now − m.date ≤ 30 min` (the v1 backfill age limit), it computes targets.
   - Edits re-run the computation; dedup prevents duplicate alerts, and a coupon whose codes were only added by an edit can still alert.
   - Forwarded coupons trigger too; alerting dedups them by origin (§4.4).
   - `ingest_many`, `rebuild-offers` and `retro_match` never emit coupon events. A test pins this.
2. **Targets.** The pure rule `coupon_targets(coupon, wishes, offers, now) -> list[CouponTarget]` lives in `velkgram/offers/domain/`. Its inputs:
   - the enabled wishes, from the wish reader offers already uses for retro matching;
   - the store's product offers in the recent window that are priced, not deleted and not sold out. This is one indexed query, capped at 500 rows.

   For each wish:
   - It keeps the offers that match the wish's terms (`matches_terms`), that the coupon applies to, and whose price is ≤ `max × 1.5`.
   - It picks the cheapest of those offers; ties go to the newest.
   - Each target carries `wish_id`, `offer_channel_id`, `offer_message_id`, `offer_price_cents`, `over_max: bool` and the applicable tier (`discount`, `min_cents`, `codes`).
3. **Event.** `CouponMatchedWish` is plain data in `velkgram/shared/events.py`, added to the `Event` union. There is **one event per coupon**, carrying every target. Its fields:
   - `coupon_channel_id`, `coupon_message_id`, `coupon_posted_at`, `coupon_received_at`;
   - `store`, `scope`;
   - `link`: the redeem link, else the coupon's main link, else None (alerting then uses the Telegram link of the coupon post);
   - `targets: tuple[CouponTarget, ...]`.

   `ingest` returns the events it produced. The builder's async worker loop then publishes them on the bus, since `ingest` itself stays synchronous.
4. **Alerting.** The handler only enqueues the event into alerting's own coupon queue and returns, so it never holds the bus.
   - A separate task processes the queue. For each target it does the following:
     - checks that the wish is still enabled;
     - builds the dedup keys (§4.4);
     - creates an alert with `kind = 'coupon'`;
     - sends it through the existing notifier, with its retries.
   - Alert fields:
     - `latency_telegram_ms = coupon_received_at − coupon_posted_at`;
     - `latency_internal_ms` = processing time;
     - `delayed_minutes = None`.

### 4.2 Offer after coupon (alerting reads offers)

1. **Port.** The port is `ActiveCoupons.for_store(store: str, since: datetime, price_cents: int | None) -> list[ActiveCoupon]`. It is defined in `alerting/ports/active_coupons.py`, and `ActiveCoupon` is defined in the alerting domain.
   - **Adapter and wiring:** the adapter lives in `alerting/adapters/offers_api.py` and calls a public query exported from `offers/__init__.py`. The apps layer wires it, the same way the wishlist reader is wired.
   - **Query:** it returns the coupon offers of that store posted at or after `since`. When `price_cents` is given, it keeps only coupons that apply to that price. Results come newest first, at most 3. The existing index `idx_offers_store_kind_feed` covers it: verify with `EXPLAIN QUERY PLAN`, and add no new index.
   - **Contract:** it is synchronous, a single indexed query, and has no timeout. Calls slower than 50 ms are logged as `active_coupons_slow`.
2. **Above-max decision.** This step runs inline, at most once per message.
   - In `_evaluate`, the evaluator first computes `classify_message(m)` and memoizes it for the message.
   - It calls the port lazily, only when some term-matched wish has a price above its max, and calls it once with `since = now − 24 h` and the message price.
   - If a coupon applies, every term-matched wish whose price satisfies `max < price ≤ max × 1.5` gets an alert, through the normal `_decide` and the v1 dedup keys. The alert is stored with `over_max = 1`.
   - Coupon posts themselves (title starting with "cupom") never take this path.
3. **Coupon line.** This step runs off the persist and dedup path.
   - In `_notify_and_finalize`, the background task that builds the text, the notifier side calls the port with the alert's price, so only coupons that apply come back. An alert with an unknown price gets no lines.
   - It adds at most 2 lines, newest first.
   - The port excludes the message being alerted.
4. **Alert first.** A port error, at either call site, is logged as `active_coupons_failed`.
   - The alert proceeds without the coupon line, or is skipped as in v1 for the above-max case.
   - It never raises into the evaluator.
5. **Race, accepted best-effort.** An offer that arrives while its coupon is still in the offers worker queue gets no coupon line or above-max alert from that coupon. This is bounded by the worker lag. The coupon-after-offer path in §4.1 still catches the pair, because its window extends to `now`.

### 4.3 Texts (pt-BR)

Money uses the existing `format_brl`. Codes appear as parsed; they are not uppercased.

**Coupon alert:**
```
🎟️ Cupom {store}: {CODE[, CODE2]} — {discount}{ a partir de R$ X}{ em {scope}}
Para "{wish name}": oferta de R$ {price}{ (acima do seu limite de R$ {max})}
{• pode não valer para todos os produtos}   ← only when scope is set
{link}
```

**Coupon line on a v1 alert:**
```
🎟️ Cupom ativo da loja: {CODE} — {discount}{ a partir de R$ X}
```

**Above-max v1 alert:** the price line gets ` (acima do seu limite de R$ {max}, mas há cupom)`.

### 4.4 Dedup (coupon alerts)

Coupon alerts use two keys. Like v1, these are an origin key and a content key, space-free and joined by a space in `alerts.dedup_key`:
- `wco:{wish_id}:{coupon_channel_id}:{coupon_message_id}`, the coupon's origin;
- `wcc:{wish_id}:{store}:{",".join(sorted(tier codes))}`, the same coupon text posted elsewhere or later.

The coupon alert rules:
- **Rule.** Both keys map to the new rule `SuppressionRule.wish_coupon`, registered in `rule_for_key`.
- **Window.** The window is 3 days, through a per-rule window in `DedupCache` (or a second instance).
- **Restart.** `warm_cache` reloads both windows.
- **Repeats.** A cheaper offer found later for the same coupon and wish does not alert again. This is intended: one coupon, one alert per wish.

### 4.5 Retry
`retry_failed` rebuilds texts from the stored message. A coupon alert instead stores its rendered text in a new `payload` column, and a retry resends that payload.

### 4.6 Web
The Alertas page shows:
- a "cupom" chip on coupon alerts, with the codes;
- an "acima do limite" chip on over-max alerts.

Links use the Telegram post links. The page does not include offers templates.

## 5. Data
- **Alerting migration `002_coupon_alerts.sql`:**
  - add `kind TEXT NOT NULL DEFAULT 'offer' CHECK (kind IN ('offer','coupon'))`;
  - add `over_max INTEGER NOT NULL DEFAULT 0`;
  - add `offer_channel_id INTEGER NULL`, `offer_message_id INTEGER NULL` and `payload TEXT NULL`.
  - For coupon alerts, `channel_id`/`message_id` point to the coupon post, and `price_cents` holds the offer price.
  - Rebuild `alert_suppressions` to add `wish_coupon` to its rule CHECK: create the new table, copy the rows, drop the old one, rename, and recreate the index, all in this one migration. Test it on a populated DB.
- **Offers:** no schema change. The public additions are `classify_message` and the active-coupons query.
- **Ownership:** alerting reads offers only through the port and the event, and offers never imports alerting.

## 6. Error handling
- **Targets or event building.** An exception is logged with the coupon ids and swallowed, so offer building continues.
- **Unknown store, no codes, sold out or deleted coupon.** None of these alerts.
- **Wish no longer enabled when processed.** The target is dropped. A terms change between match and processing is accepted.
- **Coupon deleted after its alert.** Nothing happens.

## 7. Files touched (expected)
- **shared:** `events.py`.
- **offers:**
  - `domain/coupon_targets.py` (new) and `domain/stores.py`;
  - `services/build_offer.py`, returning events, and its worker publish;
  - the queries port and SQLite adapter (the active-coupons query);
  - `__init__.py` (the public API).
- **alerting:**
  - domain: `models.py`, `dedup.py` and `format.py`;
  - ports: `active_coupons.py`, `repository.py` and `queries.py`;
  - adapters: `offers_api.py` and the sqlite repository;
  - services: `evaluate.py`, a new `coupon_alerts.py` (queue and processing) and `retry_failed.py`;
  - web: `templates/alerts.html`;
  - migrations: `002_coupon_alerts.sql`.
- **reporting:** `adapters/alerting_api.py`, if it reads alert columns.
- **apps:** collector wiring, covering the subscription, the coupon task and the port.

## 8. Testing
- **Domain, as table tests built from real posts:**
  - KaBuM! "10% OFF em Selecionados", with no minimum;
  - Shopee "R$ 10 OFF em R$ 40";
  - the multi-tier Mercado Livre post, picking the applicable tier for each price;
  - a price below the minimum;
  - a price over `max × 1.5`;
  - another store, or an unknown store;
  - an offer posted more than 3 days before the coupon;
  - an offer posted after the coupon;
  - deleted, sold-out and unpriced offers;
  - two qualifying offers, where the cheapest wins;
  - two wishes, giving two targets in one event;
  - a coupon and an offer from different channels of the same store;
  - `classify_message` with tidd.ly, amzn.to, no links, and a store taken from the title.
- **Services, with fakes:**
  - a live coupon publishes one event;
  - backfill older than 30 min, `ingest_many` and `rebuild-offers` publish nothing;
  - an edit re-runs, and dedup blocks a second alert;
  - a disabled wish gives no alert;
  - the dedup survives a restart, through warm_cache over 3 days;
  - over-max with an applicable coupon alerts;
  - over-max without a coupon, or above the ceiling, is skipped;
  - a port error keeps the v1 behavior;
  - a coupon post never takes the over-max path;
  - `retry_failed` resends a coupon alert's payload.
- **Adapter contract** for the active-coupons query, including the `price_cents` filter and the exclusion of the message being alerted.
- **Migration** applied on a populated DB.
- **Format tests** for every text in §4.3.
- **Latency:** the v1 latency test still passes. A burst of coupon events for many wishes does not delay a live `MessageReceived` alert.
- **Web:** the chips on the Alertas page.
