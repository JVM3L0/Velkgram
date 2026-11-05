# Velkgram: coupon alerts for wishes (design)

- **Status:** approved in conversation on 2026-11-05. The written spec is pending the owner's review.
- **Builds on:** `2026-11-04-velkgram-design.md` (v1 alerting), `2026-11-04-velkgram-v0.2.0-design.md` (offers, coupons, offer matches).
- **Order:** feature 1 of the sequence coupon alerts → phone notifier → JSON API → link scraping.

## 1. Purpose
Coupon posts from the deal channels ("Cupom KaBuM! 10% OFF acima de R$ 500: KORUJAO") usually apply to many products. Today the owner only learns about them by browsing the Cupons tab. The goal is to be alerted whenever a coupon can lower the price of something on the wishlist.

**Owner facts and decisions**
- The price in a post is always the final price. Never estimate or compute a price after the coupon.
- **Trigger, coupon after offer.** A coupon alerts for a wish when that wish has a matched offer from the same store in the last 3 days whose price is at least the coupon's minimum spend.
- **No max-price filter.** The wish's "Alerta até" does not filter this. An offer above the limit still counts, and the alert says so.
- **Offer after coupon.** When a matching offer arrives while a coupon from its store is active (posted in the last 24 h):
  - an alert that would fire anyway gets a coupon line;
  - an offer above "Alerta até", which today is skipped, now alerts, provided the active coupon's minimum fits its price.

## 2. Non-goals
- Computing the price after the coupon, or checking that a "Selecionados" coupon really covers the product.
- Matching coupons to wishes by name or terms. Only the store links them.
- Any change to term matching, price extraction or latency rules of v1 alerts. Only the "price above max" skip changes, and only in the case above.

## 3. Definitions
- **Coupon offer:** an offer with `kind = 'coupon'`, a known store, and not deleted.
- **Applies to a price:** a single-tier coupon applies when `coupon_min_cents` is None or ≤ the price. A multi-tier coupon applies when at least one tier's `min_cents` is None or ≤ the price. Its **applicable tier** for that price is the tier with the highest `min_cents` that is ≤ the price, with ties broken by the first in post order. The alert text shows that tier's discount, minimum and codes.
- **Repost:** the existing repost rule for offers. A repost of a coupon never alerts again.
- **Recent matched offer:** an `offer_matches` row for the wish, whose offer is `kind = 'product'`, has the same store, is not deleted, has a price, and has `posted_at` within 3 days before the coupon's `posted_at`.

## 4. Behavior

### 4.1 Coupon after offer (offers → alerting)
1. When `OfferBuilder` stores a new coupon offer, live or backfill, that is not a repost and is not an edit of an already stored coupon, it calls the pure rule `coupon_targets(coupon, recent_matches) -> list[CouponTarget]` (in `velkgram/offers/domain/`).
   - The rule keeps the matches whose price the coupon applies to.
   - It returns one target per wish: the cheapest qualifying offer, with ties going to the newest.
2. For each target, offers publishes `CouponMatchedWish` to the bus (`velkgram/shared/events.py`).
   - Its fields: `wish_id`, `coupon_channel_id`, `coupon_message_id`, `offer_channel_id`, `offer_message_id`, `offer_price_cents`, `store`, `codes: tuple[str, ...]`, `discount: str`, `min_cents: int | None`, `scope: str | None`, `link: str | None`. The link is the redeem link, else the coupon's main link, else the coupon post link.
   - This runs on the offers worker, off the v1 alert path.
3. Alerting subscribes, creates an alert with `kind = 'coupon'`, and sends it through the existing notifier, with retries and the failed/expired handling.
4. **Dedup.** The key is `wish_coupon:{wish_id}:{store}:{sorted codes}`, with a window of 3 days. A suppression is recorded like the other rules, with the new rule `wish_coupon`. An edit of the coupon post never creates a second alert. The backfill age limit of v1 applies too: no coupon alert for posts older than the v1 backfill limit.

### 4.2 Offer after coupon (alerting reads offers)
1. Alerting gains a read port, `ActiveCoupons.for_message(m: MessageData, since: datetime) -> list[ActiveCoupon]`.
   - The offers module implements it. It finds the store from the message the same way `offer_from_message` does.
   - The app wires it, like the existing wishlist reader.
   - It returns the coupon offers of that store posted at or after `since`, newest first, at most 3.
2. In the evaluator, after terms match:
   - **The price is ≤ max, or unknown.** The decision is unchanged. If the port returns coupons posted in the last 24 h, the alert text gains a coupon line.
   - **The price is above max.** Today this skips the wish. Now the evaluator calls the port, which returns coupons from the last 24 h. If any returned coupon's coupon applies to the price, the alert is created anyway. In that case `over_max = true` is recorded on the alert, and the text says the offer is above the limit but has a coupon. The usual dedup keys apply.
3. **Alert first.** A port error or timeout never blocks or delays the v1 alert. The port has a 50 ms budget. On an error, log `active_coupons_failed` and continue as if there were no coupons. In that case the above-max offer is skipped, as today.
4. **Latency.** The port runs only for wishes whose terms already matched. Its query is indexed on `(kind, store, posted_at)`. The v1 latency test must still pass.

### 4.3 Texts (pt-BR)
**Coupon alert:**
```
🎟️ Cupom {store}: {CODE[, CODE2]} — {discount}{ acima de R$ X}{ em {scope}}
Para "{wish name}": oferta de R$ {price}{ (acima do seu limite de R$ {max})}
{• pode não valer para todos os produtos — only when scope is set}
{link}
```

**Coupon line appended to a v1 alert:**
```
🎟️ Cupom ativo da loja: {CODE} — {discount}{ acima de R$ X}
```
At most 2 such lines, newest first.

**Above-max v1 alert:** the price line gains ` (acima do seu limite de R$ {max}, mas há cupom)`.

### 4.4 Web
- On the Alertas page, coupon alerts show a "cupom" chip, the coupon code(s), and a link to the offer.
- Above-max alerts show an "acima do limite" chip.

## 5. Data
- **Alerting migration `002_coupon_alerts.sql`:**
  - add `kind TEXT NOT NULL DEFAULT 'offer' CHECK (kind IN ('offer','coupon'))`;
  - add `over_max INTEGER NOT NULL DEFAULT 0`;
  - add `offer_channel_id INTEGER NULL` and `offer_message_id INTEGER NULL` (the matched offer, for coupon alerts);
  - add `wish_coupon` to the suppression rule check. This needs a table rebuild in SQLite.

  For a coupon alert, `channel_id` and `message_id` point to the coupon post, and `price_cents` holds the matched offer price.
- **Offers:** add an index `(kind, store, posted_at)` if the existing ones don't cover the port query. Check with `EXPLAIN QUERY PLAN`.
- **Ownership:** no module reads another module's tables. Alerting sees offers only through the `ActiveCoupons` port and the `CouponMatchedWish` event.

## 6. Error handling
- **Offers worker.** An exception in `coupon_targets` or in publishing is logged with the coupon's ids and swallowed. Offer building goes on.
- **Unknown store, or a coupon with no codes.** No coupon alert.
- **Wish disabled or deleted after the match.** Alerting drops the event, using the current wishlist.

## 7. Testing
- **Domain, as table tests built from real posts:**
  - KaBuM! "10% OFF em Selecionados" with no minimum;
  - Shopee "R$ 10 OFF em R$ 40";
  - the multi-tier Mercado Livre post, where the best applicable tier is chosen per price;
  - a price below the minimum;
  - a different store;
  - an unknown store;
  - an offer older than 3 days;
  - a deleted offer;
  - a coupon repost;
  - a coupon edit;
  - two qualifying offers for one wish, where the cheapest wins.
- **Services, with fakes:**
  - the builder publishes one event per wish;
  - alerting dedups, so a repost or an edit gives no second alert;
  - a disabled wish gives no alert;
  - the above-max path with a coupon alerts, and without one it is skipped;
  - a port error falls back to the v1 behavior.
- **Adapter contract** for the `ActiveCoupons` port.
- **Format tests** for every text in §4.3.
- **Latency:** the existing v1 latency test, plus a case where the port is slow (it times out at 50 ms and the alert still goes out).
- **Web:** the chips on the Alertas page.
