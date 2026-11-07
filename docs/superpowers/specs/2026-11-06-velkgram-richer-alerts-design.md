# Velkgram: richer alerts (design)

- **Status:** Approved in conversation on 2026-11-06. The written spec is waiting for the owner's review.
- **Builds on:**
  - `2026-11-05-velkgram-coupon-alerts-design.md` §3 (applicable tier), §4.1 (`CouponMatchedWish`) and §4.3 (texts);
  - `2026-11-05-velkgram-link-enrichment-design.md` §5.3 (store rules) and §6 (`product_links`);
  - `2026-11-06-velkgram-telegram-notifier-design.md` (plain-text bot messages).

## 1. Purpose
Today's Telegram alert is hard to act on:
- The product name is buried in a 300-character dump of the post.
- The store is not shown.
- A coupon shows only its code. Nothing tells the owner whether "15% OFF, limite de R$ 30" is worth anything on a R$ 1.500 product.
- The coupon alert links to the coupon post's redeem page, often a campaign list, not to the product.

This version makes every alert self-explanatory **in the first and only send**. The owner decided the following in conversation:
- **No message edits.** The alert is sent once. The real product link stays in the DB (the enricher already stores it), and the web shows it.
- The offer's own description (its first line) goes in the alert as the product name.
- The coupon alert gets the real product link when the enricher already resolved it. It usually has, because the offer arrived before the coupon. The alert keeps the redeem link too.
- **Coupon alerts must not pair a coupon with an offer whose posted price already depended on another coupon.** The owner's first real coupon alerts showed the problem. Three Mercado Livre coupons, posted hours apart, each alerted "R$ 1.517" for the same monitor. That post's price already used the coupon FAVORITO, and Mercado Livre coupons don't stack.
- **No reading of store prices.** A spike (§8) showed a plain GET reads a price only on Mercado Livre and Amazon, so the owner judged it not worth it.

## 2. Goals and non-goals
**Goals**
1. A clearer offer alert: the product name, the price and the store, each coupon with its real saving on this price, then a few extra lines from the post.
2. A clearer coupon alert: the product name, the real saving, the offer's age, the real product link and the redeem link.
3. A real saving for capped percentage coupons, used both in the text and in picking which coupon tier to show.
4. Fewer misleading coupon pairings: an offer that already used a coupon gets no other one, and only offers from the last 24 h count.
5. The web shows a "Produto" button with the real product link on offer cards and on the Alerts page.

**Non-goals**
- Editing a sent Telegram message, or sending a follow-up message.
- Reading prices from store pages, at enrichment time or when a coupon arrives (spike in §8).
- Knowing whether an offer has ended.
- Changing the enricher, its schedule, or v1 alert latency.
- Rewriting the payload of alerts that were already sent.
- A product link in the v1 offer alert. Its link has not been enriched yet when the alert goes out.

## 3. Definitions
- **Real saving** of a coupon tier on a price `p` (in cents) is `coupon_saving(tier, p) -> int | None`. It is a pure function in `velkgram/shared/deals.py` (shared by offers and alerting):
  - **The minimum is not met** (`tier.min_cents` is set and > `p`): None.
  - **Cash discount** ("R$ 90 OFF"): `min(cash, p)`.
  - **Percentage discount** ("15% OFF"): `p × pct / 100`, rounded down to the cent, then `min(…, cap_cents)` when a cap is set.
  - **No parsable discount** (an empty discount string): None.
- **Capped:** `cap_cents` is set and the uncapped percentage saving is greater than it.
- **Low cap:** capped, and saving × 100 < 5 × `p` (under 5% of the price). The constant is `LOW_CAP_PCT = 5`, kept beside `coupon_saving`.
- **Applicable tier** replaces coupon-alerts §3. Among the tiers whose minimum the price meets, the applicable tier is the one with the **largest real saving**. Ties fall back to the old rule: the highest `min_cents` (None counts as 0), then post order. A tier with no parsable discount saves 0. Example: "10% OFF em R$ 79, limite R$ 40" against "15% OFF, limite R$ 20" on R$ 300: the first saves R$ 30, the second R$ 20. The first is shown.
- **Product URL** of an offer: `product_url(store, product_id) -> str | None`, a pure function in `velkgram/offers/domain/urls.py`. It builds a canonical, affiliate-free URL:

  | store | URL |
  |---|---|
  | `amazon` | `https://www.amazon.com.br/dp/{ASIN}` |
  | `mercadolivre` | `https://produto.mercadolivre.com.br/MLB-{digits}` (id `MLB123…` → `MLB-123…`) |
  | `kabum` | `https://www.kabum.com.br/produto/{id}` |
  | `shopee` | `https://shopee.com.br/product/{shop}/{item}` (id `{shop}.{item}`) |
  | `aliexpress` | `https://pt.aliexpress.com/item/{id}.html` |
  | other | None |

  **Mercado Livre is unverified.** The spike's bot requests to both `produto.mercadolivre.com.br/MLB-…` and `/p/MLB…` were redirected to an account check. Before Task 1 is merged, the owner opens both forms for one real id in a browser. The table keeps the form that lands on the product. If neither does, `mercadolivre` returns None, because its `final_url` is the affiliate showcase (`/social/<affiliate>`), which is a list.

  An offer's **real product link** is `product_url(...)` when its `product_links` row has `kind = 'product'`. When that gives None (Magalu, other stores), the row's `final_url` is used, which is already query-free. Either value must pass `is_safe_https_url`; otherwise there is no real link. Rows that are not `product` (campaigns, lists, unknown) give no real link.

## 4. Behavior

### 4.1 Coupon parsing (offers domain)
`_CAP` in `offers/domain/coupon.py` also accepts these wordings, seen in real posts:
- "Limite de R$ 50 OFF" (today's form);
- "limite de R$ 50" (without OFF);
- "(limitado a R$ 50.00)";
- "limitado a R$ 50,00".

In a cap, "R$ 50.00" is a dot-decimal amount: a dot followed by exactly two digits and no more digits. "R$ 1.000" stays one thousand reais.

Stored coupons were parsed with the old rule. The deploy runs `velkgram rebuild-offers` once to re-parse them; that command already exists and is idempotent.

### 4.2 Offers that already used a coupon
- **Coupon-dependent offer:** a product offer whose post names a coupon code, i.e. `extract_coupons(text)` is non-empty. Example: "R$ 1517 ⏎ -CUPOM: FAVORITO". Its posted price depends on that code. The base price is unknown, and store coupons usually do not stack.
- **Coupon alerts:** a coupon-dependent offer is never a target in `coupon_targets`.
- **Offer alerts:**
  - A coupon-dependent offer gets no "cupom ativo da loja" lines.
  - It never takes the above-max path ("acima do seu limite, mas há cupom").
  - It still gets its normal alert when its posted price is within the wish's max, showing its own code (§4.3).
- **Recent window:** the coupon-after-offer window (coupon-alerts §3) shrinks from 3 days to **24 h**: product offers with `posted_at` in `[coupon.posted_at − 24 h, now]`. Both copies of the constant change: `_LOOKBACK` in `offers/domain/coupon_targets.py` and `_COUPON_LOOKBACK` in `offers/services/build_offer.py`. The offer-after-coupon window (24 h, coupon-alerts §4.2) is unchanged.

### 4.3 Offer alert text (v1 path)
The evaluator already memoizes `classify_message(m)` per message (coupon-alerts §4.2), so the store needs no new I/O. Two pure helpers are exported from `velkgram/offers/__init__.py` and used by alerting:
- `offer_title(text, store) -> str`, wrapping the existing `title_of`;
- `store_title(slug) -> str`, reading `STORE_TITLES`, with the slug itself as the fallback.

`AlertMessage` gets `title: str = ""` and `store_title: str | None = None`. Each `ActiveCoupon` gets `cap_cents: int | None = None`, carried from the applicable tier.

**Text** (lines in braces are omitted when empty):
```
🔔 {wish}
{title}
💰 {price}{ · {store}}{ (acima do seu limite de R$ X, mas há cupom)}
{🎟️ Cupom no post: CODE[, CODE2]}
{🎟️ Cupom ativo da loja: CODE — {discount}{ a partir de R$ M}{, limite de R$ C}{saving}}   ← at most 2, as today
{⏱ atrasado N min}
{extra lines}
via {channel}
{link}
```
- **No price:** the price line reads `💰 ⚠️ preço não identificado{ · {store}}`.
- **Saving suffix:** `{saving}` is ` → R$ S de desconto (P%) → ~R$ F`.
  - P has one decimal with a pt-BR comma ("2,3").
  - F = price − saving.
  - ` ⚠️ limite baixo` is appended on a low cap.
  - When the minimum is not met, the suffix is ` (não vale: mínimo R$ M)`. This happens only for a coupon whose post has no tiers, because the port already filters by price.
  - When the saving is None for another reason, there is no suffix.
- **Codes in the post** (from `extract_coupons(text)`): the post gives no terms for them, so they show code only. They no longer go in the price line.
- **Extra lines:** the post's lines after the title, in order. These lines are dropped:
  - blank lines;
  - lines whose only content is a URL;
  - lines from which `extract_price` reads a price;
  - lines that contain a code already shown;
  - the line "-Anúncio" (case- and accent-insensitive, leading "-" optional).

  Each kept line loses a leading "-" and surrounding spaces. At most 3 lines and 200 characters in all are kept; a line that would pass the limit is cut with "…". Example: "Resgate cupom do anúncio" stays.
- **The link** is unchanged: the first link in the post, else the Telegram link.
- **The 300-character dump** of the post is removed.

### 4.4 Coupon alert text
`CouponTargetData` (`shared/events.py`) gets five new fields, all with defaults so old call sites still build:
- `cap_cents: int | None = None`, from the applicable tier;
- `offer_title: str = ""`, the offer's stored `title`;
- `offer_link: str | None = None`, the offer's `main_link`;
- `product_url: str | None = None`, the real product link (§3);
- `offer_posted_at: datetime | None = None`, the offer's `posted_at`.

`OfferBuilder` fills them when it computes targets. The product link comes from **one** indexed query per coupon over the targets' `main_link`s (`product_links.url` is UNIQUE). A failure of that query only drops the product links: it logs `product_link_lookup_failed` with the error class and the event still goes out.

**Text:**
```
🎟️ Cupom {store}: CODE[, CODE2] — {discount}{ a partir de R$ M}{, limite de R$ C}{ em {scope}}
Para "{wish}": {offer title}
💰 R$ {price}{saving}{ (acima do seu limite de R$ {max})}
{📅 oferta postada há {age}}
{• pode não valer para todos os produtos}   ← only when scope is set
🔗 {Produto|Oferta}: {url}
🎟️ Resgatar cupom: {coupon link}
```
- **Age:** `{age}` is measured from `offer_posted_at` to the alert's creation:
  - under 1 h: "N min" (at least 1);
  - otherwise: "N h", rounded down.

  The line is omitted when `offer_posted_at` is None.
- **Saving suffix:** `{saving}` follows §4.3. The minimum is always met here, because a target's tier applies.
- **Title fallback:** when `offer_title` is empty, the second line reads `Para "{wish}"`.
- **The link line:**
  - `🔗 Produto: {product_url}` when a real link exists;
  - else `🔗 Oferta: {offer_link}`;
  - else `🔗 Oferta: {telegram link of the offer post}`.
- **Coupon link:** unchanged from today (`e.link`, else the Telegram link of the coupon post).
- The rendered text is stored in `alerts.payload` as today, so the web shows the new text.

### 4.5 Tier choice
`coupon_targets` (coupon-alerts §4.1.2) and the `ActiveCoupons.for_store` query (coupon-alerts §4.2.1) both use the new applicable tier (§3), through one shared helper. Its home is `offers/domain/coupon.py`, next to `best_tier`, which stays as it is for the feed headline.

The coupon content dedup key uses the chosen tier's codes. A coupon that used to alert with one tier's codes may now pick another tier. That is accepted, because the coupon-origin key still dedups the same post.

### 4.6 Web: "Produto" button
- **Offer cards** (`_offer_card.html`): `OfferCard` gets `product_url: str | None = None`, filled from the same `product_links` join that already gives `image_url`. A "Produto" button (icon `shopping_bag`) appears beside "Abrir" when it is set.
- **Alerts page** (`alerts.html`): each row gets the same button when its offer has a real link.
  - The offer of a row is `(offer_channel_id, offer_message_id)` for coupon alerts and `(channel_id, message_id)` for offer alerts.
  - The alerting web router takes an injected callable `product_links(pairs) -> dict[pair, url]`, the same pattern as `notifier_status`. `apps/web/main.py` wires it to a new public `OfferQueries.product_links(pairs)`: one query for the whole page.
  - A failure of the callable renders the page without buttons. It is logged as `product_links_failed`.
- Every href goes through the existing `safe_href`.

## 5. Error handling ("alert first")
- **Text helpers:** `offer_title`, `coupon_saving`, the extra-line filter and the formatters are pure and total: they never raise on odd text. A bad parse shows less, never fails the alert.
- **Offer alerts:** the v1 offer alert path gets no new I/O.
- **Coupon alerts:** the product-link lookup is best-effort (§4.4).
- **Web:** the product-link callable is best-effort (§4.6).

## 6. Data
- **No migration.** `coupon_tiers` JSON already stores `cap_cents`, and `product_links` already stores `store`, `product_id`, `kind` and `final_url`.
- **One-off deploy step:** `rebuild-offers`, to re-parse the new cap wordings (§4.1).

## 7. Testing
- **Coupon parsing:** each cap wording in §4.1, taken from real posts, including "R$ 50.00" against "R$ 1.000", and a line with no cap.
- **`coupon_saving`:**
  - cash;
  - percentage with and without a cap;
  - rounding down;
  - minimum not met;
  - empty discount;
  - the low-cap boundary (exactly 5% is not low).
- **Applicable tier:** the §3 example, plus a tie that falls back to the old rule.
- **`product_url`:**
  - each table row;
  - an unknown store;
  - the `final_url` fallback;
  - `not_product` gives None;
  - an unsafe URL gives None.
- **Offer alert text:** a golden test per case:
  - a full post (a real Promotom text with "-CUPOM: X", a link and "-Anúncio");
  - no price;
  - unknown store;
  - an active coupon with a low cap;
  - over max;
  - delayed;
  - the extra-line limits (3 lines, 200 characters).
- **Coupon alert text:** a golden test per case:
  - a real product link;
  - only the offer link;
  - no link at all;
  - no title;
  - with scope.
- **Coupon-dependent offers:**
  - The real FAVORITO monitor post is not a coupon target.
  - It gets no active-coupon lines.
  - It takes no above-max path.
  - It still gets a normal in-max alert.
- **Recent window:** an offer posted 23 h before the coupon is a target; one posted 25 h before is not.
- **Coupon alert age line:** 30 s gives "1 min"; 59 min gives "59 min"; 5 h 50 min gives "5 h"; no `offer_posted_at` gives no line.
- **Builder:** targets carry title, link, cap and product link from a seeded `product_links` row; a failing lookup still emits the event without product links.
- **Web:**
  - the offer card shows "Produto" only with a real link;
  - the Alerts page shows it for both alert kinds;
  - a failing callable renders the page without buttons.
- **Real check (controller and owner):**
  - the owner opens the two Mercado Livre forms in a browser (§3);
  - the controller opens one built URL per store from the table in §3 (a single GET each) and confirm it lands on the product;
  - after deploy, read one real offer alert and one real coupon alert on the phone.

## 8. Spike: store prices (2026-11-06, for the record)
13 single GETs with the enricher's headers, on real offer links:
- **Mercado Livre:** `meli.la` lands on `/social/<affiliate>`. Its `og:title` carries the featured product and its current price (for example "R$ 1.849" for the monitor whose post said R$ 1.517 with FAVORITO). Product pages redirect bots to an account check.
- **Amazon:** the first `a-offscreen` price matched the post in both samples, about 230 KB into a 1.4 MB page.
- **No price:**
  - Shopee: captcha, and the page needs JavaScript;
  - AliExpress: the link landed on a coins page;
  - Pichau and Terabyte: 403;
  - other stores: no usable data.
- **"Indisponível"** appears on every page, so availability can't be read.

Mercado Livre and Amazon are about 73% of a day's offers, but the owner judged two stores not worth it.
