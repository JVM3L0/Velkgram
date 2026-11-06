# Velkgram: link enrichment (design)

- **Status:** Approved in conversation on 2026-11-05 and revised after a context-free review. The written spec is waiting for the owner's review.
- **Builds on:** `2026-11-04-velkgram-v0.2.0-design.md` §13 ("Link scraping (next version)") and `2026-11-05-velkgram-coupon-alerts-design.md`.
- **Evidence:** A spike on a copy of the real DB (640 offers, about 35 rate-limited requests). Its observations are in §3. The samples were small, so the rules must cope with surprises.

## 1. Purpose
Offers carry affiliate and short links. 121 offers have an unknown store, and nothing tells products apart. This version follows each offer's link to find the store and the store's product id. Where the store page exposes them cheaply, it also takes a title and an image. This improves:
- the feed, which gets photos;
- the store filter and coupon matching, which see the right store;
- a wish's price chart, which is no longer polluted by a different product that matched the terms.

## 2. Goals and non-goals
**Goals**
1. Resolve each offer's `main_link` to a store and product id. This happens off the alert path, in a separate process.
2. Get a title and an image from Amazon, KaBuM!, Mercado Livre and other sites with `og:` tags.
3. Fix unknown stores so the fix survives re-ingest, edits and `rebuild-offers`.
4. Use product ids in the product page (chart and stats) and in the feed ("visto em N canais").

**Non-goals**
- Reading prices from pages, or polling them.
- Matching wishes by product id. That comes in a later version.
- Running JavaScript, or getting around bot protection.
- Downloading or hosting images.
- Any change to the collector, `OfferBuilder`, the alert path or v1 latency.
- Re-evaluating coupon alerts when a store gets fixed later. A coupon whose store was unknown during its 30-min live window never alerts. That is accepted.

## 3. Spike observations
| Host (count) | Needs redirects? | Needs body? | Product id | Title / image |
|---|---|---|---|---|
| `www.amazon.com.br` (233, `/dp/<ASIN>`) | no | yes, up to 512 KB | ASIN from the URL | `<meta name="title">` / `<title>` at about 58 KB; `"hiRes":"https://…"` at about 370 KB. No `og:` tags. Gzip. The page is 1.7 MB. |
| `cutt.ly` (101 unknown + 8) | yes (1 hop) | per final store | per final store (seen: KaBuM!, Amazon `/gp/aw/d/`, Magalu `/p/`) | per final store |
| `tidd.ly` (28 unknown + 4) | yes (2 hops) | yes, 16 KB | KaBuM! `/produto/<id>/` | `og:title`, `og:image` in the first 2 KB |
| `meli.la` (151) | yes (1 hop, to `mercadolivre.com.br/social/<affiliate>?ref=…`) | yes, 512 KB | `"item_id":"MLB<digits>"` in the body | `og:title` (strip ` - R$ …`), `og:image` in the first 6 KB |
| `s.click.aliexpress.com` (32) | the first hop only (its `Location` has `productId=`) | no | from the first hop | none (needs JavaScript) |
| `s.shopee.com.br` (31) | yes (1 hop, to `/<slug>/<shopid>/<itemid>`) | no | `<shopid>.<itemid>` | none (single-page app) |
| Magalu | yes; the final page returns 403 | no | `/p/<id>/` (an optional path prefix is allowed) | none |
| `link.amazon`, `go.promotom.com.br` | yes | no | none: campaign or coupon pages | none |
| other hosts (`terabyteshop`, `pichau`, `store.vivo`, …) | yes | yes, 64 KB | none | `og:title` / `og:image` if present |

## 4. Architecture
- **Owner:** the offers module. New code:
  - **`offers/domain/links.py`:** pure per-store rules.
  - **`offers/domain/urls.py`:** pure URL helpers: strip the query, `host_of`, `is_safe_url` and `is_safe_https_url`. This moves the core of `safe_href` out of `offers/web/format.py`, which then imports it.
  - **`offers/services/enrich.py`:** the loop.
  - **`offers/ports/fetcher.py`:** the `Fetcher` port.
  - **`offers/adapters/http/fetcher.py`:** an httpx-based `HttpxFetcher`, wired only by `apps/cli.py`.
- **Process:** a new compose service, `enricher`, runs `velkgram enrich` from the same image and DB volume.
  - **Restart and startup:** `restart: unless-stopped`; `depends_on: migrate: service_completed_successfully`; `stop_grace_period: 45s`.
  - **Healthcheck:** none in this version. The status page shows the enricher's last run (§5.7).
  - **SIGTERM:** the loop stops between URLs.
- **Dependency:** `httpx` moves from the dev group to `[project].dependencies`, and `uv.lock` is refreshed. No brotli: requests send `Accept-Encoding: gzip, deflate`.
- **Module rules:**
  - No other module reads `product_links`.
  - A new import-linter contract forbids `httpx` in `offers.domain` and `offers.services`.

## 5. Behavior

### 5.1 Link identity and discovery
- **The link table is keyed by URL.** A `product_links` row is keyed by `url`: the offer's `main_link` exactly as stored (it is already extracted and trimmed), so every join compares equal strings. Offers join links by `offers.main_link = product_links.url`.
  - Offers get **no `link_id` column**, so an edit that changes `main_link` points to the right row automatically.
  - Coupon offers join on `main_link` as well.
- **`OfferBuilder` is untouched.** The enricher discovers work itself, in small batches.
  - It reads `main_link` values of non-deleted offers that have no `product_links` row, newest `MAX(posted_at)` first, `LIMIT 50`.
  - It inserts them as `pending`.
  - There is no separate backfill: old offers are simply older in the same queue.
  - An index on `offers(main_link)` keeps this query cheap.
- **Picking the next row.** After discovery, the loop picks the next row with `status = 'pending'` or `next_try_at <= now`:
  - Rows on paused hosts (§5.2) are skipped, so one blocked store doesn't stop the others.
  - The order is the newest offer first.
  - When nothing is due, it sleeps until the earliest `next_try_at`, at most 10 s.
- **Reusing known products.** If the rules can tell the store and product id from the URL alone (Amazon `/dp/`, Shopee, Magalu), and another `done` row already has the same `(store, product_id)` with a title, the loop copies its title and image instead of fetching.

### 5.2 Fetching (adapter)
- **Request.** `HttpxFetcher.fetch(url, plan, before_request, budget_for) -> FetchOutcome(final_url, hops, status, content_type, body, answered_by)`; `before_request` lets the service throttle and pause every hop's host.
  - **Client:** `follow_redirects=False`; redirects are followed manually, at most 5.
  - **Relative `Location` headers** are resolved with `urljoin`. Non-`http(s)` schemes, repeated URLs (loops) and hosts that resolve to loopback, private, link-local or unspecified IPs (checked with `ipaddress` after DNS) stop the chain, with status `invalid`.
  - **Headers:** a generic desktop User-Agent and `Accept-Language: pt-BR`.
  - **Timeouts:** 10 s per request and 30 s for the whole chain.
- **Body.** It is read only when `body_budget > 0` and the content type is HTML. The stream is closed once the budget is reached, and the whole page is never drained.
  - Decoding uses the charset from the header or a `<meta charset>`, falling back to UTF-8 with `errors="replace"`, so a multibyte character cut at the limit never raises.
- **Throttle per host.** At most 1 request every **2 s** per host, for **every hop's host**.
  - A 403 or 429 pauses **that host** for 30 min.
  - The service enforces this with an injected clock and sleep.
- **Logging.** The `httpx` and `httpcore` loggers are set to WARNING in the enricher. Enricher logs carry only the host, the status and the exception class name: never a full URL, a query string or exception text. A test checks that no log record contains a query string.

### 5.3 Per-store rules (pure)
`resolve(original_url, result) -> LinkInfo(store, product_id, title, image_url, kind)`. The store comes from `store_of(final_url)`, and the rules then run in this order:
1. Look for the product id in the URLs: the final URL first, then each hop.
2. If there is still no id and the body was read, look for it in the body. This is where Mercado Livre's `"item_id":"MLB…"` comes from.
3. Decide the kind:
   - `product` when an id was found;
   - `not_product` when the body or the URL was read and the host is a known store but no id was found (campaign, category, coupon pages);
   - `unknown` otherwise, for example when the body was blocked (403) or the host is not a store.
4. Read the title and the image only for `product`, or for unknown hosts with `og:` tags:
   - **Amazon:** the title comes from `<meta name="title">` or `<title>`, with the `Amazon.com.br:` prefix and the ` : Amazon.com.br…` suffix stripped. The image is the first `"hiRes":"https://…"`, else `data-old-hires`. A captcha or "Robot Check" page counts as blocked.
   - **Mercado Livre:** `og:title` with a trailing ` - R$ 1.299,00` / ` - R$ 16,14` / ` - R$ 1.299` stripped, plus `og:image`.
   - **Others:** `og:title` and `og:image`.
   - **Cleanup:** titles are HTML-unescaped, whitespace-collapsed and capped at 200 characters. Images must pass `is_safe_https_url`.

**Per-host request budget**, taken from §3:
- Amazon direct: no redirects, 512 KB of body.
- AliExpress: the first hop only, no body.
- Shopee and Magalu: follow redirects, no body.
- Mercado Livre: follow redirects, 512 KB of body.
- KaBuM!: follow redirects, 16 KB of body.
- Others: follow redirects, 64 KB of body.

### 5.4 Writing results
Each URL is written in **its own short transaction**: one link-row update, plus at most one store-fix `UPDATE`.

- **Status after a fetch:**
  - **`done`:** a usable result, including `not_product` and `unknown`.
  - **Network error, timeout or 5xx:** retry after 5 min, then 30 min, then 6 h. After the 4th failed attempt the row becomes `failed`, and it is never retried automatically.
  - **403 or 429:** the row becomes `blocked`, and whatever the URL gave is kept. It is retried once after 24 h, and the host pause applies. While a host is paused, its rows don't count attempts.
  - **`invalid`:** a bad scheme, a loop or a private IP is a final `done` with kind `unknown`.
- **Stored values:**
  - `final_url` is stored **without its query string or fragment**, because that is where affiliate tokens live.
  - Hops are never stored; ids are parsed from them first.
  - The `url` column necessarily keeps the original link, which is already in `offers.main_link`. This is accepted: nothing new is exposed, and no page renders `url` or `final_url`.
- **Store fix:**
  - The enricher sets the store with `UPDATE offers SET store = ? WHERE main_link = ? AND store IS NULL`.
  - The offers repository upsert keeps a fixed store across re-ingest, edits and `rebuild-offers`, with `store = COALESCE(excluded.store, (SELECT store FROM product_links WHERE url = excluded.main_link))`.
  - A known store is never overwritten.
  - Tests cover rebuild and edit.
- **Side effects of a fixed store:** it feeds the feed filter, `stores_seen`, coupon stores and counts, and `recent_store_offers` for later coupons. Earlier coupons are not re-evaluated (§2).

### 5.5 Product page (chart and stats)
- **Dominant product.** The pure function `dominant_product(keys: Sequence[tuple[str, str] | None]) -> tuple[str, str] | None` lives in the domain.
  - **Input:** one item per comparable priced match of the wish, over **all** of the wish's matches, not just the selected range. Each item is the match's `(store, product_id)`, or None when the link is unknown.
  - **Result:** the most frequent pair, but only when at least **3** matches have a pair, that pair holds at least 60 % of them, and it is strictly ahead of the runner-up. Otherwise it returns None.
- **Other products.** Matches with a different known pair are "outro produto". They:
  - are excluded from the chart points and the stats, like non-comparable ones;
  - stay in the match list with a muted chip "outro produto", shown as `MatchCard.other_product: bool`;
  - still count in `match_count`, as before.
- **Where it is computed and applied.** `SqliteOfferQueries` computes the dominant pair once per wish and applies it in `priced_points`, `_points`, `summaries` (the wish list sparkline and last price) and `matches_page`. This keeps the list and the product page consistent.
- Matches without a pair are unaffected. With no dominant pair, nothing changes.

### 5.6 Feed
- **Image.**
  - **When:** only when the link has `kind = product`, a product id and an image.
  - **Markup:** `<img loading="lazy" decoding="async" referrerpolicy="no-referrer" alt="">`, with fixed dimensions so nothing shifts.
  - **Broken images** show an empty fixed box on the surface background (no CSS-only failure detection exists). There is no inline script.
  - **The offer's own title** is unchanged.
- **"visto em N canais".**
  - **Hiding rule:** an SQL predicate next to `_NOT_REPOST` hides an offer `o` when a newer offer `x` exists that matches it on all of these:
    - the same link `(store, product_id)`, both non-null;
    - the same non-null `price_cents`;
    - `kind = 'product'`, not deleted;
    - `x.posted_at` in `(o.posted_at, o.posted_at + 24 h]`.
  - **Chip:** the visible offer gets "visto em N canais". N is the number of distinct channels among the offers it hides plus itself, counted by a subquery. The chip's `title` lists them.
  - **Interactions:**
    - it composes with `_NOT_REPOST`; forwards are counted once, as reposts;
    - it is applied only to the unfiltered feed (no search, price, store or channel filter, `priced_only` off), so a filtered view never loses an offer to a sibling the filter would not show; the hiding offer must itself be visible (not a repost);
    - it applies to the cursor, `count_feed_after` and paging alike, because it is part of the WHERE clause.
  - **Performance:** a test measures the feed query with the join on the volume fixture and keeps the 150 ms limit.

### 5.7 Status
`velkgram enrich` updates a small heartbeat after each URL: the last run time and the counts by status. The Status page shows "Enriquecimento de links: última execução há X; N pendentes, M bloqueados".

## 6. Data (offers migration `006_product_links.sql`)
- **`product_links` table:**

  | Column | Type | Notes |
  |---|---|---|
  | `id` | `INTEGER` | `PRIMARY KEY` |
  | `url` | `TEXT` | `NOT NULL UNIQUE` |
  | `final_url` | `TEXT` | |
  | `store` | `TEXT` | |
  | `product_id` | `TEXT` | |
  | `title` | `TEXT` | |
  | `image_url` | `TEXT` | |
  | `kind` | `TEXT` | `NOT NULL DEFAULT 'unknown'`, `CHECK (kind IN ('product','not_product','unknown'))` |
  | `status` | `TEXT` | `NOT NULL DEFAULT 'pending'`, `CHECK (status IN ('pending','done','failed','blocked'))` |
  | `attempts` | `INTEGER` | `NOT NULL DEFAULT 0` |
  | `next_try_at` | `TEXT` | |
  | `fetched_at` | `TEXT` | |
  | `created_at` | `TEXT` | `NOT NULL` |

- **Indexes:**
  - `product_links (status, next_try_at)`;
  - `product_links (store, product_id)`;
  - `offers (main_link)`.
- **Extra columns (from plan review):** `offer_posted_at` (discovery priority), `host` and `final_host` (paused-host filtering in SQL) and `blocks` (403/429 count, separate from `attempts`). A row is `failed` after the 4th error or the 2nd block.
- **Heartbeat:** a `link_enrich_state` single-row table for §5.7.
- **Retention:** link rows are kept forever and never deleted, including rows with no offers left. Text purge doesn't touch them, and `rebuild-offers` doesn't either.

## 7. Error handling
- **Enricher stopped or crashed:** nothing else is affected, and the work waits.
- **Unexpected exception for one URL:** logged as `link_enrich_failed` with the host and the exception class, then counted as an attempt.
- **Odd or unrecognized markup:** the rules never raise. They return what they found, possibly nothing.
- **Parsing:** regex and `html.parser` on the excerpt only.
- **Locks:** short transactions and the existing `busy_timeout` of 5 s. A test with a concurrent writer checks that the collector's upsert never times out while the enricher runs.

## 8. Testing
- **Domain:**
  - **Rule tables** from trimmed real fixtures under `tests/fixtures/links/`:
    - Amazon: ASIN, the prefix and suffix, `hiRes`, and a captcha page;
    - KaBuM!;
    - Mercado Livre: the social page with `item_id`, and price-suffix variants;
    - AliExpress: the first hop;
    - Shopee;
    - Magalu: 403, and a path prefix;
    - `link.amazon` and `go.promotom` as `not_product`;
    - an unknown host with og tags;
    - a cutt.ly interstitial that gives 200 with no hop, which yields `unknown`.
  - **`dominant_product`:** the threshold, a tie, fewer than 3 matches, and None.
  - **URL helpers:** normalize, strip the query, `is_safe_https_url`.
- **Service, with a fake fetcher and a fake clock:**
  - discovery order;
  - one fetch per URL even when many offers share it;
  - a URL whose offers are all deleted is skipped;
  - the throttle on every hop's host;
  - a paused host doesn't block the others;
  - the retry schedule and the `failed` state;
  - reuse by `(store, product_id)`;
  - the store fix touches only unknown stores and survives rebuild and edit;
  - the loop survives an exception;
  - SIGTERM stops it between URLs;
  - log redaction.
- **Adapter:**
  - **Logic,** with `httpx.MockTransport`:
    - relative `Location`;
    - more than 5 hops;
    - a loop;
    - a bad scheme;
    - a private IP;
    - the body budget, with a multibyte character cut at the limit;
    - non-HTML content;
    - 403 and 429.
  - **Real gzip and early close,** with a stdlib `http.server` on localhost.
- **Contracts:** link rows on the fake and on SQLite. Migration test on a populated DB.
- **Queries:**
  - the feed collapse: same id and price within 24 h, a different price, the channel filter, paging across a collapsed group;
  - "outro produto" across `priced_points`, `_points`, `summaries` and `matches_page`;
  - the feed latency with the join.
- **Web:** the image appears only for products; the "outro produto" chip; "visto em N canais"; the status line.
- **Concurrency:** a concurrent writer while the enricher runs.
- **CLI:** `velkgram enrich --once --limit N` processes N due rows on a temp DB with a fake fetcher.
- **Real-world check after implementation:** the controller runs `--once` on a copy of the real DB, with at least 5 URLs per major host. The pass criteria:
  - the store is fixed for at least 90 % of cutt.ly and tidd.ly;
  - an id is found for at least 90 % of Amazon, KaBuM! and Mercado Livre;
  - no exceptions.
