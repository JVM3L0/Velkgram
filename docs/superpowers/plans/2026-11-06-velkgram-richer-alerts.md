# Richer Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The offer and coupon alerts show the product name, the store, each coupon's real saving and the offer's age. The coupon alert also carries the real product link, misleading coupon pairings stop, and the web gets "Produto" buttons.

**Architecture:**
- **Pure helpers** compute the real saving, the applicable tier and the product URL. They live in `shared/deals.py` and `offers/domain/`.
- **The offers module** fills new `CouponTargetData` fields and exposes product links through its public API.
- **Alerting** formats the new texts. The apps layer injects the offers helpers, as it already does for `classify_message`.
- No migration, no new process, and no message edits.

**Tech Stack:** Python 3.13, uv, SQLite, FastAPI + Jinja2, pytest, pyright, import-linter.

**Spec:** `docs/superpowers/specs/2026-11-06-velkgram-richer-alerts-design.md`. Cite it as RA. Each task names the RA sections it needs.

## Global Constraints
- Code, names, tests, logs and commits are in English. Every alert and web string is pt-BR, copied verbatim from RA.
- Money is `int` cents and goes through `format_brl`. Never use floats for money. The percentage shown is the only float, formatted with one decimal and a pt-BR comma.
- Module boundaries:
  - alerting never imports `velkgram.offers.<submodule>`, only the package `velkgram.offers` (public API), and only from adapters. Services get offers helpers by injection.
  - offers never imports alerting.
  - `shared.deals` imports no business module.
- "Alert first": every new helper is total (it never raises on odd text). Each new lookup is best-effort and logs the error class:
  - `product_link_lookup_failed` in the builder;
  - `product_links_failed` on the web.
- Checks before every commit:
  ```
  uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports && uv run pytest -q
  ```
- Never touch `data/`, `.env` or the live instance. Never push.

## Review Focus
1. A coupon line in "R$ 1.234,56" or "R$ 50.00" form must not be misread. "R$ 1.000" is one thousand reais. Pinned in Task 1.
2. A percentage coupon with no cap must not be flagged "limite baixo", and exactly 5% is not low. Pinned in Task 1.
3. An alert for a post with no text lines besides price and link must not print empty lines or "None". Pinned in Task 4 golden tests.
4. A retention-purged offer (`text` None) must not crash target selection. It counts as having no codes. Pinned in Task 3.
5. A wish with an apostrophe or quotes in its name, or a title with `"`, renders verbatim (the text is plain, not HTML). Pinned in Task 4 golden tests.

---

### Task 1: Real saving, cap wordings and the applicable tier

RA sections: §3 (real saving, capped, low cap, applicable tier), §4.1, §4.5.

**Files:**
- Modify:
  - `velkgram/shared/deals.py`
  - `velkgram/offers/domain/coupon.py` (`_CAP`)
  - `velkgram/offers/domain/coupon_targets.py` (`applicable_tier`, `AppliedTier`)
  - `velkgram/offers/ports/queries.py` (`ActiveCouponView`)
  - `velkgram/offers/adapters/sqlite/queries.py` (`active_coupons`)
  - `velkgram/alerting/domain/models.py` (`ActiveCoupon`)
  - `velkgram/alerting/adapters/offers_api.py`
  - `velkgram/shared/events.py` (`CouponTargetData.cap_cents`)
- Test:
  - `tests/shared/test_deals_saving.py` (new)
  - `tests/offers/domain/test_coupon.py`
  - `tests/offers/domain/test_coupon_targets.py`
  - the existing active-coupons adapter test

**Interfaces:**
- Produces, in `velkgram/shared/deals.py`:
  - `LOW_CAP_PCT = 5`
  - `@dataclass(frozen=True, slots=True) class Saving: cents: int; capped: bool; low: bool`
  - `def coupon_saving(discount: str, min_cents: int | None, cap_cents: int | None, price_cents: int) -> Saving | None`. It returns None when the minimum is not met or the discount doesn't parse. `low` is `capped and cents * 100 < LOW_CAP_PCT * price_cents`.
  - `def min_not_met(min_cents: int | None, price_cents: int) -> bool`
- Produces, in `coupon_targets.py`:
  - `AppliedTier(discount, min_cents, codes, cap_cents: int | None = None)`;
  - `applicable_tier(...)` with the same signature, choosing by real saving (RA §3) and carrying `cap_cents`.
- Produces `ActiveCouponView.cap_cents: int | None = None`, `ActiveCoupon.cap_cents: int | None = None` and `CouponTargetData.cap_cents: int | None = None`. All are new last fields with defaults.

- [ ] **Step 1: Write failing tests**
  - **`coupon_saving`:**
    - `("R$ 90 OFF", 69900, None, 100000)` → `Saving(9000, False, False)`;
    - `("R$ 90 OFF", None, None, 5000)` → cents 5000;
    - `("15% OFF", None, None, 151700)` → 22755;
    - `("15% OFF", None, 4000, 151700)` → `Saving(4000, True, True)`;
    - `("20% OFF", None, 5000, 10000)` → `Saving(2000, False, False)`;
    - `("10% OFF", 7900, None, 5000)` → None;
    - `("", None, None, 1000)` → None;
    - `("R$ 9,90 OFF", None, None, 10000)` → 990;
    - boundary: `("50% OFF", None, 500, 10000)` → `Saving(500, True, False)` (exactly 5% is not low);
    - rounding down: `("15% OFF", None, None, 999)` → 149.
  - **`_tiers`** (via `coupon_deal`) reads `cap_cents == 5000` from each of:
    - "20% OFF em compras (limitado a R$ 50.00): BF20OFF"
    - "15% OFF, limite de R$ 50: X1"
    - "15% OFF, Limite de R$ 50 OFF: X2"
    - "10% OFF limitado a R$ 50,00: X3"

    It reads `cap_cents == 100000` from "10% OFF, Limite de R$ 1.000 OFF: X4". A line without a cap gives `cap_cents is None`.
  - **`applicable_tier`:**
    - tiers `[("10% OFF", 7900, 4000, ("A",)), ("15% OFF", None, 2000, ("B",))]` at 30000 → codes `("A",)`, cap 4000 (the RA §3 example);
    - equal savings → the old rule (higher min, then first);
    - nothing applicable → None.
  - **The active-coupons adapter** carries `cap_cents` into `ActiveCoupon`.
- [ ] **Step 2:** Run the tests and confirm they fail.
- [ ] **Step 3: Implement.**
  - `_CAP` accepts `(?:limite\s+de|limitado\s+a)\s+R\$\s*<amount>(?:\s*OFF)?`. In the amount, a dot followed by exactly two digits and then a non-digit is a decimal separator.
  - Parse the discount string with the forms `_discount_text` produces: `"{n}% OFF"`, `"R$ {n} OFF"` and `"R$ {n},{cc} OFF"`.
  - `applicable_tier` treats a tier whose saving is None, but whose minimum is met, as saving 0.
- [ ] **Step 4:** Run the full checks and confirm they pass.
- [ ] **Step 5:** Commit `feat(offers): real coupon saving, cap wordings and tier choice by saving`.

### Task 2: Product URLs and the web "Produto" buttons

RA sections: §3 (product URL table, Mercado Livre note), §4.6, §5.

**Files:**
- Modify:
  - `velkgram/offers/domain/urls.py`
  - `velkgram/offers/ports/queries.py` (`OfferCard.product_url`, `OfferQueries.product_links`)
  - `velkgram/offers/ports/repository.py` (`OfferRepository.product_urls`)
  - `velkgram/offers/adapters/sqlite/queries.py`
  - `velkgram/offers/adapters/sqlite/repository.py`
  - `velkgram/offers/web/router.py` and `templates/_offer_card.html`
  - `velkgram/alerting/web/router.py` and `templates/alerts.html`
  - `velkgram/apps/web/main.py`
- Test:
  - `tests/offers/domain/test_urls.py`
  - `tests/offers/adapters/…` (the repository and queries tests)
  - `tests/offers/web/…`
  - `tests/alerting/web/…`

**Interfaces:**
- Produces, in `offers/domain/urls.py`:
  - `def product_url(store: str | None, product_id: str | None) -> str | None`, which follows the RA §3 table exactly; Mercado Livre is `https://www.mercadolivre.com.br/p/{id}`.
  - `def real_product_url(store: str | None, product_id: str | None, kind: str | None, final_url: str | None) -> str | None`. It returns None unless `kind == "product"`. Otherwise it returns `product_url(...)` or `final_url`, and the result must pass `is_safe_https_url`.
- Produces `OfferRepository.product_urls(main_links: Sequence[str]) -> dict[str, str]` (one query, main_link → real URL; empty input does no query).
- Produces `OfferQueries.product_links(pairs: Sequence[tuple[int, int]]) -> dict[tuple[int, int], str]` (one query keyed by `(channel_id, message_id)` of offers).
- Produces `OfferCard.product_url: str | None = None`, filled in the existing feed SELECT from the `pl` join.
- Changes the alerting `build_router(...)`: it gains a keyword `product_links: Callable[[sqlite3.Connection, Sequence[tuple[int, int]]], dict[tuple[int, int], str]] | None = None`.
  - Row key: `(offer_channel_id, offer_message_id)` for coupon alerts (when set), else `(channel_id, message_id)`.
  - Row field `product_href`.
  - It is wired in `apps/web/main.py` via `SqliteOfferQueries(conn).product_links`.

- [ ] **Step 1: Write failing tests**
  - **`product_url`:**
    - amazon `B0C8814GKB` → `https://www.amazon.com.br/dp/B0C8814GKB`;
    - mercadolivre `MLB62870034` → `https://www.mercadolivre.com.br/p/MLB62870034`;
    - kabum `123` → `https://www.kabum.com.br/produto/123`;
    - shopee `898761179.44718674582` → `https://shopee.com.br/product/898761179/44718674582`;
    - aliexpress `1005001` → `https://pt.aliexpress.com/item/1005001.html`;
    - magalu → None; None store → None.
  - **`real_product_url`:**
    - magalu, kind product, final `https://www.magazineluiza.com.br/x/p/abc/` → that URL;
    - `not_product` → None;
    - final `http://…` (not https) with no canonical → None.
  - **Repository and queries:** seed `product_links` rows (product, not_product), then check `product_urls`, `product_links` and `OfferCard.product_url`.
  - **Web:**
    - the offer card renders a "Produto" link (icon `shopping_bag`) only when `product_url` is set;
    - the Alerts page renders it for an offer alert and for a coupon alert (keyed by the offer pair);
    - a callable that raises renders the page without buttons and logs `product_links_failed`.
- [ ] **Step 2:** Run the tests and confirm they fail.
- [ ] **Step 3:** Implement. Hrefs go through `safe_href` on the offers side. The alerting side shows only values the callable returns; they are already https-checked.
- [ ] **Step 4:** Run the full checks and confirm they pass.
- [ ] **Step 5:** Commit `feat(offers): real product urls and "Produto" buttons on feed and alerts`.

### Task 3: Coupon alerts (targets, event fields and text)

RA sections: §4.2 (coupon-dependent offers, 24 h window), §4.4, §5.

**Files:**
- Modify:
  - `velkgram/offers/domain/coupon_targets.py` (`_LOOKBACK`, `_is_candidate`)
  - `velkgram/offers/services/build_offer.py` (`_COUPON_LOOKBACK`, `_queue_coupon_event`)
  - `velkgram/shared/events.py` (`CouponTargetData` fields)
  - `velkgram/alerting/domain/format.py` (`format_coupon_alert`)
  - `velkgram/alerting/services/coupon_alerts.py`
- Test:
  - `tests/offers/domain/test_coupon_targets.py`
  - `tests/offers/services/…` (the builder test)
  - `tests/alerting/domain/test_format.py`
  - `tests/alerting/services/…` (the coupon alerts test)

**Interfaces:**
- Consumes `coupon_saving`, `AppliedTier.cap_cents` (Task 1) and `OfferRepository.product_urls` (Task 2).
- Produces the remaining `CouponTargetData` fields, after `cap_cents`, all with defaults: `offer_title: str = ""`, `offer_link: str | None = None`, `product_url: str | None = None`, `offer_posted_at: datetime | None = None`.
- Produces the new `format_coupon_alert` keyword-only signature:
  ```python
  def format_coupon_alert(*, store_title: str, codes: tuple[str, ...], discount: str,
      min_cents: int | None, cap_cents: int | None, scope: str | None, wish_name: str,
      offer_title: str, offer_price_cents: int, max_price_cents: int, over_max: bool,
      offer_age: timedelta | None, product_url: str | None, offer_link: str, coupon_link: str) -> str
  ```
  `offer_link` is already resolved by the caller: the target's `offer_link`, else `telegram_link` of the offer post.

- [ ] **Step 1: Write failing tests**
  - **Targets:**
    - an offer with `coupons=("FAVORITO",)` is never a target;
    - an offer with `text=None` and no coupons can be a target;
    - posted 23 h before the coupon → target; 25 h → not;
    - the target carries `offer_title`, `offer_link` (= `main_link`), `offer_posted_at` and `cap_cents`.
  - **Builder:**
    - with a seeded `product_links` product row for the target's `main_link`, the event's target has `product_url`;
    - a repository whose `product_urls` raises still emits the event, with `product_url=None`, and logs `product_link_lookup_failed`.
  - **Golden texts** (exact strings, RA §4.4):

    (a) Product link, capped and low. Store "Mercado Livre", codes `("OFFNOML",)`, `"15% OFF"`, no min, cap 4000, no scope, wish "Monitor", title "Smart Tv Aoc 50'' 50U7066", price 170900, max 200000, not over, age 5 h 50 min, product `https://www.mercadolivre.com.br/p/MLB1`, coupon link `https://mercadolivre.com/sec/2U6U32Q`:
    ```
    🎟️ Cupom Mercado Livre: OFFNOML — 15% OFF, limite de R$ 40,00
    Para "Monitor": Smart Tv Aoc 50'' 50U7066
    💰 R$ 1.709,00 → R$ 40,00 de desconto (2,3%) → ~R$ 1.669,00 ⚠️ limite baixo
    📅 oferta postada há 5 h
    🔗 Produto: https://www.mercadolivre.com.br/p/MLB1
    🎟️ Resgatar cupom: https://mercadolivre.com/sec/2U6U32Q
    ```
    (b) No product URL: the link line is `🔗 Oferta: {offer_link}`.

    (c) Empty title: the second line is `Para "Monitor"`.

    (d) With scope "Selecionados", min 7900, over max with max 150000:
      - the head line ends `— 15% OFF a partir de R$ 79,00, limite de R$ 40,00 em Selecionados`;
      - the price line ends ` (acima do seu limite de R$ 1.500,00)`;
      - the line `• pode não valer para todos os produtos` follows the age line.

    (e) Age 30 s → `há 1 min`; age None → no 📅 line.
- [ ] **Step 2:** Run the tests and confirm they fail.
- [ ] **Step 3: Implement.**
  - The age text uses the alert's `created_at` minus `offer_posted_at`.
  - `_queue_coupon_event` makes one `product_urls` call over the targets' `offer_link`s, then `dataclasses.replace`s each target.
- [ ] **Step 4:** Run the full checks and confirm they pass.
- [ ] **Step 5:** Commit `feat(alerting): richer coupon alerts with product link and offer age`.

### Task 4: Offer alerts (text and coupon-dependent rule)

RA sections: §4.2 (offer-alert bullets), §4.3, §5.

**Files:**
- Modify:
  - `velkgram/alerting/domain/models.py` (`AlertMessage.title`, `AlertMessage.store_title`)
  - `velkgram/alerting/domain/format.py` (`format_alert`, `format_coupon_line`, a new `extra_lines`)
  - `velkgram/alerting/services/evaluate.py`
  - `velkgram/offers/__init__.py` (export `offer_title`, `store_title`)
  - `velkgram/offers/domain/title.py` (add `offer_title` and `store_title` wrappers)
  - `velkgram/apps/collector/collector.py` (wiring)
- Test:
  - `tests/alerting/domain/test_format.py`
  - `tests/alerting/services/…` (the evaluator test)
  - `tests/apps/test_collector_assembly.py` (one end-to-end text check)

**Interfaces:**
- Consumes `coupon_saving` and `ActiveCoupon.cap_cents` (Task 1).
- Produces, in `offers/domain/title.py`, re-exported from `velkgram.offers`:
  - `offer_title(text: str, store: str | None) -> str` (it wraps `title_of`);
  - `store_title(slug: str) -> str` (`STORE_TITLES.get(slug, slug)`).
- Produces new keyword parameters on `Evaluator.__init__`:
  - `title_of: Callable[[str, str | None], str]`, default: the first non-blank line, stripped;
  - `store_title: Callable[[str], str]`, default: the identity.

  `collector.py` wires them to `offer_title` and `store_title`.
- Produces `AlertMessage.title: str = ""` and `AlertMessage.store_title: str | None = None`.
- Produces `extra_lines(text: str, title: str, codes: tuple[str, ...]) -> tuple[str, ...]` in `alerting/domain/format.py`, following the RA §4.3 rules: skip the title line itself, keep at most 3 lines and 200 characters, cut with "…".

- [ ] **Step 1: Write failing tests**
  - **Golden full post.** Wish "Monitor", channel "Promotom", store "Mercado Livre", text:
    ```
    Monitor Gamer LG UltraGear Curvo 34"- QuadHD 2K -34G600A

    R$ 1517
    -CUPOM: FAVORITO

    https://meli.la/2ZeTaW5

    -Anúncio
    ```
    It gives exactly:
    ```
    🔔 Monitor
    Monitor Gamer LG UltraGear Curvo 34"- QuadHD 2K -34G600A
    💰 R$ 1.517,00 · Mercado Livre
    🎟️ Cupom no post: FAVORITO
    via Promotom
    https://meli.la/2ZeTaW5
    ```
  - **Golden active coupon, low cap.** A post without codes, price 151700, and an `ActiveCoupon("15% OFF", None, cap 4000, ("ESPECIALML",))`. The line is `🎟️ Cupom ativo da loja: ESPECIALML — 15% OFF, limite de R$ 40,00 → R$ 40,00 de desconto (2,6%) → ~R$ 1.477,00 ⚠️ limite baixo`.
  - **Other golden cases:**
    - min not met (an active coupon with min 200000 and no tiers) → the suffix ` (não vale: mínimo R$ 2.000,00)`;
    - no price → `💰 ⚠️ preço não identificado · Mercado Livre`;
    - unknown store → no ` · ` part;
    - over max → the suffix ` (acima do seu limite de R$ 1.400,00, mas há cupom)` on the 💰 line;
    - delayed 7 → `⏱ atrasado 7 min` before the extra lines;
    - "Resgate cupom do anúncio" kept as an extra line;
    - 5 extra lines → only 3;
    - a 300-character line → cut to 200 characters ending "…".
  - **`extra_lines`:** a post that is only title, price and link → `()`.
  - **Evaluator:**
    - a post whose text has a coupon code makes no `ActiveCoupons.for_store` call;
    - it creates no over-max alert even with an active coupon;
    - it still alerts within max;
    - `AlertMessage` carries `title` and `store_title` from the injected callables.
- [ ] **Step 2:** Run the tests and confirm they fail.
- [ ] **Step 3: Implement.**
  - The coupon-dependent check is `bool(extract_coupons(m.text))`, done at the top of `_lookup` (return `[]`), so both the lines and the over-max path skip it.
  - Remove the `text[:300]` dump and the price-line " com cupom" suffix.
  - `format_coupon_line(c, price_cents)` gains the price parameter for the saving suffix.
- [ ] **Step 4:** Run the full checks and confirm they pass.
- [ ] **Step 5:** Commit `feat(alerting): richer offer alerts and skip store coupons for coupon-dependent posts`.

---

## Execution notes (controller)
- **Order:** 1 → 2 → 3 → 4. Task 3 needs Tasks 1 and 2; Task 4 needs Task 1.
- **Deploy (owner):**
  1. `docker compose build && docker compose up -d`;
  2. `docker compose run --rm migrate velkgram rebuild-offers` (RA §6);
  3. the enricher must be running.
- **Real check (RA §7):** one GET per built store URL, except Mercado Livre (owner-confirmed). Then the owner reads one real offer alert and one real coupon alert.
