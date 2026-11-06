# Velkgram: link enrichment (design)

- **Status:** approved in conversation on 2026-11-05. Awaiting the owner's review of this written spec.
- **Builds on:** `2026-11-04-velkgram-v0.2.0-design.md` §13 ("Link scraping (next version)").
- **Evidence:** a spike on a copy of the real DB (640 offers, about 35 rate-limited requests). The findings are summarized in §3.

## 1. Purpose
Offers carry affiliate and short links. 121 of them have an unknown store, and products can't be told apart. This version follows each offer's link and identifies the store and the store's product id. When the store's page exposes them cheaply, it also takes the product title and image. The data improves three things the owner already uses:
- the feed shows product photos;
- the store filter and coupon matching see the right store;
- a wish's price chart is no longer polluted by a different product that happened to match the terms.

## 2. Goals and non-goals
### Goals
1. Resolve each offer's `main_link` to a final URL, a store and a product id, off the alert path, in a separate process.
2. Get a title and an image where the spike showed that plain HTTP works: Amazon, KaBuM!, Mercado Livre.
3. Fix `offers.store` when it is unknown and the resolved link gives a store.
4. Use product ids in the product page (chart and stats) and in the feed ("visto em N canais").

### Non-goals
- Reading prices from store pages, or tracking prices by polling. The price in a post is always the truth.
- Matching wishes by product id ("track this exact product"). That is planned for a later version.
- Running JavaScript (Shopee, AliExpress) or getting around bot protection (403, captchas).
- Downloading or hosting images. The app stores only the image URL.
- Any change to the alert path or to v1 latency.

## 3. Spike findings (binding facts)
| Link host (count in DB) | Resolution | Product id | Title and image |
|---|---|---|---|
| `www.amazon.com.br` (233, direct `/dp/<ASIN>`) | none needed | ASIN from the URL | No `og:` tags. `<title>` / `<meta name="title">` at about 58 KB, image in the embedded JSON `"hiRes":"…"` at about 370 KB. The response is gzip, so decompress it. The page is 1.7 MB. |
| `cutt.ly` (101 unknown + 8) | 1 hop | from the final URL (mostly KaBuM!, some Amazon `/gp/aw/d/<ASIN>` and Magalu `/p/<id>/`) | depends on the final store |
| `tidd.ly` (28 unknown + 4) | 2 hops to KaBuM! `/produto/<id>/…` | KaBuM! id | `og:title` and `og:image` in the first 2 KB |
| `meli.la` (151) | 1 hop to `mercadolivre.com.br/social/<affiliate>?ref=…`, an affiliate page with no MLB in the URL | `"item_id":"MLB<digits>"` in the embedded JSON | `og:title`, with a ` - R$ x,yy` suffix to strip, and `og:image` in the first 6 KB |
| `s.click.aliexpress.com` (32) | the **first** hop's `Location` carries `productId=<13–16 digits>` (URL-encoded), and the final page is an app promo | from the first hop | none (JavaScript only) |
| `s.shopee.com.br` (31) | 1 hop to `shopee.com.br/<slug>/<shopid>/<itemid>` | `<shopid>.<itemid>` | none (single-page app) |
| Magalu (via cutt.ly) | the final page returns 403 | `/p/<id>/` from the URL | none |
| `link.amazon`, `go.promotom.com.br` | campaign, category and coupon pages | none | none (not a product) |

## 4. Architecture
- **Owner:** the offers module. It already owns offers, links and stores. New code:
  - `offers/domain/links.py`: pure per-store rules that read a URL and a page excerpt;
  - `offers/services/enrich.py`: the enrichment loop;
  - `offers/ports/fetcher.py`: the port;
  - `offers/adapters/http/fetcher.py`: the adapter, built on httpx.
- **Process:** a new docker compose service, `enricher`, running `velkgram enrich`. It uses the same image and DB volume as the collector and web.
  - It never runs inside the collector, so a slow page, a hang or a network error can't touch alerts.
  - SQLite WAL already handles writes from several processes. Every connection sets a busy timeout.
- **Dependency:** `httpx` becomes a runtime dependency. It is already a dev dependency, used by the tests.
- **Module rules:** unchanged. No other module reads the new table. The web pages read enrichment through the offers queries.

## 5. Behavior
### 5.1 Work selection
1. The enricher picks the next links to process, in this order:
   - links never tried, from the newest offers first;
   - then links due for a retry.

   Several offers may share one link, so the unit of work is a **distinct URL**.
2. A new offer gets its link row when `OfferBuilder` stores it, with status `pending`. Existing offers get their rows from a one-time backfill step that runs when the enricher starts and is idempotent.
3. The loop runs one URL at a time. It sleeps 10 s when there is nothing to do.

### 5.2 Fetching (adapter)
- **Requests:** a generic desktop browser User-Agent, `Accept-Language: pt-BR`, gzip and brotli decoded by httpx, a timeout of 15 s per request, and at most 5 redirects, followed manually.
- **Redirects are recorded:** the adapter returns `FetchResult(final_url, hops: tuple[str, ...], status, body_prefix: bytes)`. `hops` holds every `Location` it saw. AliExpress needs this, because its product id is in the first hop.
- **Size limit:** it reads the body only up to **512 KB** after decompression, then closes the stream.
- **When the body is not fetched:**
  - when the domain rule needs no page (Amazon id-only, Shopee, AliExpress), it resolves redirects with `GET` and stops reading the body;
  - for direct Amazon `/dp/` links, it does no redirect step.
- **Politeness:**
  - at most 1 request per registrable domain every **2 s**, enforced in the service through an injected clock and sleep;
  - a 403 or 429 from a domain pauses that domain for **30 min**.

### 5.3 Per-store rules (pure, `offers/domain/links.py`)
`resolve(store_hint, original_url, result) -> LinkInfo(store, product_id, title, image_url, kind)`. `kind` is one of `product`, `not_product` or `unknown`.

| Store | Product id | Title | Image |
|---|---|---|---|
| amazon | `/dp/<ASIN>` or `/gp/aw/d/<ASIN>` or `/gp/product/<ASIN>` (10 chars `[A-Z0-9]`) | `<meta name="title">` or `<title>`, with the trailing ` : Amazon.com.br…` suffix stripped | first `"hiRes":"https://…"`, else the `landingImage` `data-old-hires` |
| kabum | `/produto/<digits>/` | `og:title` | `og:image` |
| mercadolivre | `MLB-?<digits>` in the URL, else the first `"item_id":"MLB<digits>"` in the body | `og:title` with the ` - R$ …` suffix stripped | `og:image` |
| aliexpress | `productId=<digits>` or `/item/<digits>.html` in any hop or the final URL | none | none |
| shopee | `/<slug>/<shopid>/<itemid>` or `-i.<shopid>.<itemid>` gives `"<shopid>.<itemid>"` | none | none |
| magalu | `/p/<id>/` | `og:title` when status is 200 | `og:image` when status is 200 |
| others | none (`kind = unknown`) | `og:title` if present | `og:image` if present |

- **Not a product:** a URL that matches a store but no product id pattern is `not_product`. This covers campaign, category, `/promocao/`, `/social/…` without an item id, `coin-index` and the like.
- **Text cleanup:** titles are HTML-unescaped, whitespace-collapsed and capped at 200 chars. Image URLs must be `https://` and pass `safe_href`.
- **Store from the final URL:** the existing `store_of` runs on the final URL. Hosts that are not in the store list keep `store = None`.

### 5.4 Writing results
- **Successful resolution:** the link row stores `final_url`, `store`, `product_id`, `title`, `image_url`, `kind`, `status = done`, `fetched_at`.
- **Network error, timeout or 5xx:** `attempts += 1`, then retry after 5 min, 30 min and 6 h. After 4 attempts the row is `failed` and is never retried automatically.
- **403 or 429:** the row is `blocked` and is retried once after 24 h. Whatever the URL already gave (store, id) is still saved.
- **Store fix:** offers with `store IS NULL` that point to a link row with a store get `offers.store` set. This happens only when the offer's store is unknown, never by overwriting a known store.
- **Coupon offers:** their links are also resolved, for the store fix. No title or image is shown for them.

### 5.5 Product page (chart and stats)
- **Dominant product:** for a wish's comparable priced matches, the dominant product is the `product_id` with the most matches, if it holds at least **60 %** of the matches that have an id.
- **Other products:** matches with a different known id are marked "outro produto". They are shown in the match list with a muted chip and are excluded from the chart and stats, like non-comparable ones.
- **Matches without an id** stay in the chart and stats, as today.
- **No dominant product:** without one, nothing changes.

### 5.6 Feed
- **Image:** cards show the image when the link has one, as `<img loading="lazy" decoding="async" referrerpolicy="no-referrer" alt="">` with fixed dimensions, so there is no layout shift. A broken image hides itself through a CSS fallback, with no inline script.
- **Same product, several channels:** offers with the same `(store, product_id)` and the same price, posted within **24 h** of the newest one, collapse into one card with "visto em N canais", the same way reposts collapse today. Only the newest is shown, and the chip lists the channels in its `title`.
- **Store chip:** it shows the fixed store.

## 6. Data
- **Offers migration `006_product_links.sql`** (the number follows the existing offers migrations):
  - **new table `product_links`:**
    - `id INTEGER PRIMARY KEY`;
    - `url TEXT NOT NULL UNIQUE`;
    - `final_url TEXT`;
    - `store TEXT`;
    - `product_id TEXT`;
    - `title TEXT`;
    - `image_url TEXT`;
    - `kind TEXT NOT NULL DEFAULT 'unknown' CHECK (kind IN ('product','not_product','unknown'))`;
    - `status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done','failed','blocked'))`;
    - `attempts INTEGER NOT NULL DEFAULT 0`;
    - `next_try_at TEXT`;
    - `fetched_at TEXT`;
    - `created_at TEXT NOT NULL`;
  - **indexes:** `(status, next_try_at)` and `(store, product_id)`;
  - **new column `offers.link_id INTEGER NULL`**, referencing `product_links(id)`, with an index.
- **Retention:** link rows are kept forever, like summaries. They hold no message text.
- **Rebuild:** `rebuild-offers` keeps `link_id`, and re-links by `main_link` if needed.

## 7. Error handling
- **Enricher crash or stop:** offers and alerts are unaffected. Pending rows wait.
- **Unexpected exception for one URL:** it is logged as `link_enrich_failed` with the URL host (never the full affiliate URL with its tokens) and counted as an attempt.
- **Page markup the rules don't recognize:** the rules return what they found, possibly nothing, and they never raise.
- **Malformed HTML:** the rules use regex and `html.parser` on the excerpt only. They don't use lxml and they never execute anything.

## 8. Testing
- **Domain:**
  - **Per-store rules,** as table tests built from saved real fixtures: trimmed copies of the spike pages kept under `tests/fixtures/links/`, with their HTML heads and relevant JSON snippets. Cover:
    - Amazon (ASIN, title suffix, hiRes);
    - KaBuM! (og);
    - Mercado Livre (the social page with `item_id`, and the title price suffix);
    - AliExpress (`productId` in the first hop);
    - Shopee (ids from the URL);
    - Magalu 403 (id only);
    - `link.amazon` and `go.promotom` (`not_product`);
    - an unknown host.
  - **Dominant product:** 60 % threshold, ties, no ids.
  - **Feed collapse:** same id, same price, within 24 h. A different price does not collapse.
- **Service, with a fake fetcher and a fake clock:**
  - order: new before backfill;
  - one request per domain every 2 s;
  - a 403 pauses the domain;
  - the retry schedule and the `failed` state after 4 attempts;
  - the store fix sets only unknown stores;
  - the backfill is idempotent;
  - the loop survives an exception.
- **Adapter, against a local test HTTP server, with no internet:**
  - redirects are recorded in `hops`;
  - more than 5 redirects stop;
  - gzip is decoded;
  - the 512 KB cap holds;
  - the timeout holds;
  - 403 and 429 are reported.
- **Contracts:** link rows on both the fake and SQLite. Migration test on a populated DB.
- **Web:** the image is rendered with lazy and no-referrer, the "outro produto" chip appears, and "visto em N canais" appears.
- **Assembly:** `velkgram enrich --once` processes the pending rows of a temp DB with a fake fetcher.
- **Real-world check:** after implementation, a controller run on a copy of the real DB processes 50 URLs and reports the success rate per host. The rates should match §3.
