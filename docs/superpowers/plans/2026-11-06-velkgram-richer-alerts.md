# Richer Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alerts get the product name, the store, each coupon's real saving and the offer's age. The coupon alert also gets the real product link, misleading coupon pairings stop, and the web gets "Produto" buttons.

**Architecture:**
- **Pure helpers** compute the real saving, the applicable tier and the product URL. They live in `shared/deals.py` and `offers/domain/`.
- **The offers module** fills the new `CouponTargetData` fields and exposes product links through its public API.
- **Alerting** formats the texts. The apps layer injects the offers helpers, as it already does for `classify_message`.
- No migration, no new process, no message edits.

**Tech Stack:** Python 3.13, uv, SQLite, FastAPI and Jinja2, pytest, pyright, import-linter.

**Spec:** `docs/superpowers/specs/2026-11-06-velkgram-richer-alerts-design.md`, cited as RA. Each task names the RA sections it needs.

## Global Constraints
- **Language.** Code, names, tests, logs and commits are in English. Every alert and web string is pt-BR, copied verbatim from RA or from this plan.
- **Money.** Money is `int` cents, shown through `format_brl`. The percentage shown is `f"{saving * 100 / price:.1f}".replace(".", ",")`; it is the only float.
- **Module boundaries.**
  - alerting imports only the package `velkgram.offers` (its public API), and only from adapters or the apps layer. Alerting services get offers helpers by injection.
  - offers never imports alerting.
  - `shared.deals` imports no business module.
- **"Alert first."** New helpers are total: they never raise on odd text. New lookups are best-effort and log the error class:
  - `product_link_lookup_failed` in the builder;
  - `product_links_failed` on the web.
- **Changed behavior means changed tests.** When an existing test pins behavior that RA changes, rewrite that test to the new behavior. Don't keep the old logic. Each task lists the tests known to change.
- **Checks before every commit:**
  ```
  uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports && uv run pytest -q
  ```
- **Never** touch `data/`, `.env` or the live instance. Never push.

## Review Focus
1. **Cap amounts.** "R$ 50.00" and "R$ 12.50" are decimals, "R$ 1.000" is one thousand, and "R$ 1.000,50" is both. `_MONEY` (used by minimum spend and discounts) must not change. Pinned in Task 1.
2. **"Limite baixo" boundary.** A percentage coupon with no cap is never flagged "limite baixo", and exactly 5% is not low. Pinned in Task 1.
3. **Sparse posts.** A post with no lines besides title, price and link prints no empty line and no "None". A blank title omits the title line. Pinned in Task 4.
4. **Retries.** A retried offer alert (the bot was down) still shows title and store. Pinned in Task 4.
5. **Plain text.** A wish name or title with quotes renders verbatim: the text is plain, not HTML. Pinned in Tasks 3 and 4.

---

### Task 1: Real saving, cap wordings and the applicable tier

RA: §3 (real saving, capped, low cap, applicable tier), §4.1, §4.5.

**Files:**
- Modify:
  - `velkgram/shared/deals.py`
  - `velkgram/offers/domain/coupon.py` (`_CAP`, `_SCOPE`)
  - `velkgram/offers/domain/coupon_targets.py` (`AppliedTier`, `applicable_tier`, and the `CouponTargetData(...)` construction)
  - `velkgram/offers/ports/queries.py` (`ActiveCouponView`)
  - `velkgram/offers/adapters/sqlite/queries.py` (`active_coupons`)
  - `velkgram/alerting/domain/models.py` (`ActiveCoupon`)
  - `velkgram/alerting/adapters/offers_api.py`
  - `velkgram/shared/events.py` (`CouponTargetData.cap_cents`)
- Test:
  - `tests/shared/test_deals_saving.py` (new)
  - `tests/offers/domain/test_coupon.py`
  - `tests/offers/domain/test_coupon_targets.py`
  - `tests/alerting/adapters/test_offers_api.py`

**Interfaces:**
- **Produces, in `velkgram/shared/deals.py`:**
  - `LOW_CAP_PCT = 5`.
  - `@dataclass(frozen=True, slots=True) class Saving: cents: int; capped: bool; low: bool`.
  - `def min_not_met(min_cents: int | None, price_cents: int) -> bool`. It is true only when `min_cents` is set and greater than the price; a minimum equal to the price is met.
  - `def coupon_saving(discount: str, min_cents: int | None, cap_cents: int | None, price_cents: int) -> Saving | None`.
    - It returns None when `min_not_met`, or when the discount doesn't parse.
    - It parses the forms `_discount_text` produces: `"{n}% OFF"`, `"R$ {n} OFF"`, `"R$ {n},{cc} OFF"`.
    - Cash: `min(cash, price)`, never capped.
    - Percentage: `price * n // 100`; then, when `cap_cents` is set and smaller, the cap, with `capped=True`.
    - `low = capped and cents * 100 < LOW_CAP_PCT * price_cents`.
- **Produces, in `coupon_targets.py`:**
  - `AppliedTier(discount, min_cents, codes, cap_cents: int | None = None)`.
  - `applicable_tier(...)`, same signature. Among the tiers whose minimum the price meets, it picks the largest `coupon_saving` (None counts as 0). Ties go to the old rule (highest `min_cents`, None = 0, then the first). It carries the tier's `cap_cents`. Without tiers it builds one tier from `(discount, min_cents, None, codes)`, as today.
- **Produces new last fields, all defaulting to None:** `ActiveCouponView.cap_cents`, `ActiveCoupon.cap_cents` and `CouponTargetData.cap_cents`.
  - `coupon_targets` sets `cap_cents=tier.cap_cents`.
  - `active_coupons` passes `tier.cap_cents` when `price_cents` is given, and None otherwise.
  - `OffersActiveCoupons` copies it.

- [ ] **Step 1: Write failing tests**
  - **`coupon_saving`:**
    - `("R$ 90 OFF", 69900, None, 100000)` → `Saving(9000, False, False)`
    - `("R$ 90 OFF", None, None, 5000)` → `Saving(5000, False, False)`
    - `("R$ 9,90 OFF", None, None, 10000)` → cents 990
    - `("15% OFF", None, None, 151700)` → `Saving(22755, False, False)`
    - `("15% OFF", None, 4000, 151700)` → `Saving(4000, True, True)`
    - `("20% OFF", None, 5000, 10000)` → `Saving(2000, False, False)`
    - `("50% OFF", None, 500, 10000)` → `Saving(500, True, False)` (exactly 5% is not low)
    - `("15% OFF", None, None, 999)` → cents 149 (rounds down)
    - `("10% OFF", 7900, None, 5000)` → None (minimum not met)
    - `("10% OFF", 5000, None, 5000)` → cents 500 (minimum equal to price is met)
    - `("", None, None, 1000)` → None
  - **Cap parsing** (via `coupon_deal("Cupom X", text, [])`, reading `tiers[0].cap_cents`):
    - "20% OFF em compras (limitado a R$ 50.00): BF20OFF" → 5000
    - "15% OFF, limite de R$ 50: XA" → 5000
    - "15% OFF, Limite de R$ 50 OFF: XB" → 5000
    - "10% OFF limitado a R$ 50,00: XC" → 5000
    - "10% OFF, Limite de R$ 12.50 OFF: XD" → 1250
    - "10% OFF, Limite de R$ 1.000 OFF: XE" → 100000
    - "10% OFF, Limite de R$ 1.000,50 OFF: XF" → 100050
    - "10% OFF: XG" → None
  - **Scope** of "20% OFF em compras (limitado a R$ 50.00): BF20OFF" → `"compras"`. Today the scope swallows the parenthesis; this pins the fix.
  - **`applicable_tier`:**
    - tiers `[CouponTier("10% OFF", 7900, 4000, ("A",)), CouponTier("15% OFF", None, 2000, ("B",))]` at 30000 → codes `("A",)`, cap 4000;
    - two tiers saving the same → the higher minimum;
    - no tier applies → None;
    - no tiers and an empty discount with the minimum met → an `AppliedTier` (saving 0).
  - **The adapter** copies `cap_cents` into `ActiveCoupon`.
- [ ] **Step 2: Rewrite the existing tests that the new tier rule changes.**
  - `tests/offers/domain/test_coupon_targets.py::test_mercado_livre_picks_the_tier_by_price`: with the fixture from `tests/offers/domain/test_coupon.py`, the "30% OFF em R$ 1, limite R$ 500" tier now wins at both prices.
    - At 69900 it saves 20970, more than R$ 90.
    - At 15000 it saves 4500.
    - Expect its discount, minimum and codes, and rename the test to `..._by_real_saving`.
  - Also update any `test_queries` or `active_coupons` test that pins the old tier.
- [ ] **Step 3:** Run the tests and confirm the new ones fail.
- [ ] **Step 4: Implement.**
  - Add a separate `_CAP_MONEY = r"R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{2})|\.(\d{2})(?!\d))?"` and a `_cap_cents(match)` helper. Don't change `_MONEY` or `_cents`.
  - `_CAP` is `\b(?:limite\s+de|limitado\s+a)\s+{_CAP_MONEY}(?:\s*OFF)?`, case-insensitive.
  - `_SCOPE` also stops at `(`. Strip the result.
- [ ] **Step 5:** Run the full checks and confirm they pass.
- [ ] **Step 6:** Commit `feat(offers): real coupon saving, cap wordings and tier choice by saving`.

### Task 2: Product URLs and the web "Produto" buttons

RA: §3 (product URL table, Mercado Livre note), §4.6, §5.

**Files:**
- Modify:
  - `velkgram/offers/domain/urls.py`
  - `velkgram/offers/ports/queries.py` (`OfferCard.product_url`, `OfferQueries.product_links`)
  - `velkgram/offers/ports/repository.py` (`OfferRepository.product_urls`)
  - `velkgram/offers/adapters/sqlite/queries.py`
  - `velkgram/offers/adapters/sqlite/repository.py`
  - `velkgram/offers/web/router.py` (`CardView.product_href`, `card_view`) and `templates/_offer_card.html`
  - `velkgram/alerting/web/router.py` and `templates/alerts.html`
  - `velkgram/apps/web/main.py`
  - `tests/fakes/repositories.py`
- Test:
  - `tests/offers/domain/test_urls.py`
  - `tests/offers/adapters/` (the SQLite repository and queries tests: SQLite-only, like `dominant_key`)
  - `tests/offers/web/`
  - `tests/alerting/web/`

**Interfaces:**
- **Produces, in `offers/domain/urls.py`:**
  - `def product_url(store: str | None, product_id: str | None) -> str | None`. It follows the RA §3 table exactly; Mercado Livre is `https://www.mercadolivre.com.br/p/{id}`.
  - `def real_product_url(store: str | None, product_id: str | None, kind: str | None, final_url: str | None) -> str | None`.
    - It returns None unless `kind == "product"`.
    - Otherwise it returns `product_url(...)`, or else `final_url`.
    - Whatever it returns must pass `is_safe_https_url`; otherwise it returns None.
- **Produces `OfferRepository.product_urls(main_links: Sequence[str]) -> dict[str, str]`.**
  - One query joining `product_links` by `url`. The result maps main_link to the real URL and includes only links that have one.
  - Empty input runs no query.
  - The in-memory fake gets a public `product_url_map: dict[str, str]` (empty by default). Its `product_urls` returns the requested keys found in that map.
- **Produces `OfferQueries.product_links(pairs: Sequence[tuple[int, int]]) -> dict[tuple[int, int], str]`.** One query over `offers o LEFT JOIN product_links pl ON pl.url = o.main_link`, keyed by `(channel_id, message_id)`. Empty input gives `{}`.
- **Produces `OfferCard.product_url: str | None = None`.**
  - Add `pl.store AS pl_store, pl.product_id AS pl_product_id, pl.kind AS pl_kind, pl.final_url AS pl_final_url` beside `_IMAGE` in both SELECTs that use it (the feed, and the product page's match cards).
  - Compute `real_product_url(...)` in `_card` when those keys exist.
  - Coupon cards stay None and get no button.
  - `CardView` gets `product_href: str | None = None`, filled with `safe_href(card.product_url)`.
- **Changes the alerting `build_router(...)`:** it gains `product_links: Callable[[sqlite3.Connection, Sequence[tuple[int, int]]], dict[tuple[int, int], str]] | None = None`.
  - The router collects every row's pair first and calls once per page.
  - The pair is `(offer_channel_id, offer_message_id)` for a coupon alert when both are set, else `(channel_id, message_id)`.
  - Row field `product_href`.
  - If the call raises, log `product_links_failed` and use `{}`.
- **`apps/web/main.py`** wires `product_links=lambda conn, pairs: SqliteOfferQueries(conn).product_links(pairs)`.
- **Button markup** (both templates): `<a class="button small border" href="{{ href }}" rel="noopener noreferrer" target="_blank"><i aria-hidden="true">shopping_bag</i><span>Produto</span></a>`, placed before "Abrir". On the Alerts page it goes in both the compact cell and the wide cell, like "Abrir".

- [ ] **Step 1: Write failing tests**
  - **`product_url`:**
    - amazon `B0C8814GKB` → `https://www.amazon.com.br/dp/B0C8814GKB`
    - mercadolivre `MLB62870034` → `https://www.mercadolivre.com.br/p/MLB62870034`
    - kabum `123456` → `https://www.kabum.com.br/produto/123456`
    - shopee `898761179.44718674582` → `https://shopee.com.br/product/898761179/44718674582`
    - aliexpress `1005006571234567` → `https://pt.aliexpress.com/item/1005006571234567.html`
    - magalu → None; a None store → None
  - **`real_product_url`:**
    - magalu, kind product, final `https://www.magazineluiza.com.br/x/p/abc123/` → that URL
    - kind `not_product` → None
    - an unknown store with final `http://x.com/p` (not https) → None
  - **SQLite:** seed one `product` row and one `not_product` row, then check:
    - `product_urls` gives only the first;
    - `product_links` is keyed by the offer pair;
    - feed `OfferCard.product_url` is set for the product row and None for the other.
  - **Web:**
    - the offer card shows "Produto" only when `product_href` is set;
    - the Alerts page shows it for an offer alert and for a coupon alert, keyed by the offer pair;
    - a callable that raises renders the page with no button and logs `product_links_failed`.
- [ ] **Step 2:** Run the tests and confirm they fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full checks and confirm they pass.
- [ ] **Step 5:** Commit `feat(offers): real product urls and "Produto" buttons on feed and alerts`.

### Task 3: Coupon alerts (targets, event fields, saving helper and text)

RA: §4.2 (coupon-dependent offers, the 24 h window), §4.3 (only the saving suffix rules), §4.4, §5.

**Files:**
- Modify:
  - `velkgram/offers/domain/coupon_targets.py` (`_LOOKBACK`, `_is_candidate`)
  - `velkgram/offers/services/build_offer.py` (`_COUPON_LOOKBACK`, `_queue_coupon_event`)
  - `velkgram/shared/events.py` (`CouponTargetData`)
  - `velkgram/alerting/domain/format.py` (new `format_saving` and `format_age`, the new `format_coupon_alert`)
  - `velkgram/alerting/services/coupon_alerts.py`
- Test:
  - `tests/offers/domain/test_coupon_targets.py`
  - `tests/offers/services/test_build_offer.py`
  - `tests/alerting/domain/test_format.py`
  - `tests/alerting/services/test_coupon_alerts.py`
  - `tests/apps/test_collector_assembly.py`

**Interfaces:**
- **Consumes:** `coupon_saving`, `min_not_met`, `AppliedTier.cap_cents` (Task 1); `OfferRepository.product_urls` and the fake's `product_url_map` (Task 2).
- **Produces `CouponTargetData` fields after `cap_cents`, all with defaults:**
  - `offer_title: str = ""` (the offer's `title`);
  - `offer_link: str | None = None` (the offer's `main_link`);
  - `product_url: str | None = None`;
  - `offer_posted_at: datetime | None = None`.
- **Produces, in `alerting/domain/format.py`:**
  - `def format_saving(discount: str, min_cents: int | None, cap_cents: int | None, price_cents: int) -> str`. Task 4 uses it too.
    - If `min_not_met`: ` (não vale: mínimo R$ M)`.
    - Else, with a saving S: ` → R$ S de desconto (P%) → ~R$ F`, plus ` ⚠️ limite baixo` when low. F = price − S, and every amount goes through `format_brl`.
    - Else `""`.
  - `def format_age(age: timedelta) -> str`.
    - A negative age is clamped to 0.
    - Under 1 h: `f"{max(1, minutes)} min"`.
    - Otherwise: `f"{hours} h"`, rounded down.
  - The new keyword-only signature:
    ```python
    def format_coupon_alert(*, store_title: str, codes: tuple[str, ...], discount: str,
        min_cents: int | None, cap_cents: int | None, scope: str | None, wish_name: str,
        offer_title: str, offer_price_cents: int, max_price_cents: int, over_max: bool,
        offer_age: timedelta | None, product_url: str | None, offer_link: str,
        coupon_link: str) -> str
    ```
    - The head is `🎟️ Cupom {store}: {codes joined ", "}`, followed by:
      - ` — {discount}` when the discount is non-empty;
      - ` a partir de R$ M` when there is a minimum;
      - `, limite de R$ C` when there is a cap;
      - ` em {scope}` when there is a scope.
    - The caller resolves `offer_link`: the target's `offer_link`, else `telegram_link(offer_channel_id, offer_message_id)`. It resolves `coupon_link` as today: `e.link`, else the Telegram link of the coupon post.
    - `offer_age = alert created_at − offer_posted_at`, or None.
- **Targets:**
  - Coupon-dependent means `bool(offer.coupons)`. It reads the stored column, never `text`.
  - `_is_candidate` adds `not offer.coupons`.
  - `_LOOKBACK` and `_COUPON_LOOKBACK` become `timedelta(hours=24)`.
- **Builder:** `_queue_coupon_event` collects the targets' non-None `offer_link`s and calls `self._repo.product_urls(...)` once. Then it uses `dataclasses.replace` to set `product_url` on each target. If that call raises, it logs `product_link_lookup_failed` with `error=type(e).__name__` and sends the event without product URLs.

- [ ] **Step 1: Write failing tests**
  - **Targets:**
    - an offer with `coupons=("FAVORITO",)` is never a target;
    - an offer posted exactly 24 h before the coupon is a target, and one posted 24 h + 1 s before is not;
    - a target carries `offer_title`, `offer_link` (equal to `main_link`), `offer_posted_at` and `cap_cents`.
  - **Builder:**
    - with `repo.product_url_map[main_link] = "https://www.amazon.com.br/dp/B0C8814GKB"`, the target has that `product_url`;
    - monkeypatching `product_urls` to raise still emits the event, with `product_url=None`, and logs `product_link_lookup_failed`.
  - **`format_age`:**
    - 30 s → `1 min`; 59 min → `59 min`; 60 min → `1 h`; 5 h 50 min → `5 h`;
    - −2 min → `1 min`.
  - **Golden (a).** store "Mercado Livre", codes `("OFFNOML",)`, "15% OFF", no minimum, cap 4000, no scope, wish "Monitor", title `Smart Tv Aoc 50'' 50U7066`, price 170900, max 200000, not over max, age 5 h 50 min, product `https://www.mercadolivre.com.br/p/MLB1`, offer link `https://meli.la/x`, coupon link `https://mercadolivre.com/sec/2U6U32Q`:
    ```
    🎟️ Cupom Mercado Livre: OFFNOML — 15% OFF, limite de R$ 40,00
    Para "Monitor": Smart Tv Aoc 50'' 50U7066
    💰 R$ 1.709,00 → R$ 40,00 de desconto (2,3%) → ~R$ 1.669,00 ⚠️ limite baixo
    📅 oferta postada há 5 h
    🔗 Produto: https://www.mercadolivre.com.br/p/MLB1
    🎟️ Resgatar cupom: https://mercadolivre.com/sec/2U6U32Q
    ```
  - **Golden (b).** Same as (a) with `product_url=None`: the fifth line is `🔗 Oferta: https://meli.la/x`.
  - **Golden (c).** Same as (a) with `offer_title=""`: the second line is `Para "Monitor"`.
  - **Golden (d).** Wish `Monitor "34"`, title `LG 34" Curvo`, "10% OFF", minimum 7900, cap 4000, scope "Selecionados", price 151700, max 150000, over max, age None, no product, offer link `https://meli.la/y`:
    ```
    🎟️ Cupom Mercado Livre: OFFNOML — 10% OFF a partir de R$ 79,00, limite de R$ 40,00 em Selecionados
    Para "Monitor "34"": LG 34" Curvo
    💰 R$ 1.517,00 → R$ 40,00 de desconto (2,6%) → ~R$ 1.477,00 ⚠️ limite baixo (acima do seu limite de R$ 1.500,00)
    • pode não valer para todos os produtos
    🔗 Oferta: https://meli.la/y
    🎟️ Resgatar cupom: https://mercadolivre.com/sec/2U6U32Q
    ```
  - **`format_saving`:**
    - a minimum not met gives ` (não vale: mínimo R$ 2.000,00)`;
    - a discount that doesn't parse gives `""`.
- [ ] **Step 2: Rewrite the existing tests that pin the old text or window.**
  - `tests/alerting/domain/test_format.py`: the `_coupon` helper (keyword arguments as above) and every coupon-alert assertion (`oferta de …`, the position of `• pode não valer`, the last line).
  - `tests/alerting/services/test_coupon_alerts.py`: lines ~100 and ~109. The last line is now `🎟️ Resgatar cupom: <link>`.
  - `tests/apps/test_collector_assembly.py:~396`: it asserts `'Para "Teclado": oferta de R$ 99,00'`.
  - `tests/offers/domain/test_coupon_targets.py::test_recent_window_starts_three_days_before_the_coupon`: replace it with the 24 h boundary test.
  - `tests/offers/services/test_build_offer.py::test_product_posted_two_and_a_half_days_before_the_coupon_is_a_target`: rewrite it to 23 h (target), plus a 2.5-day case (not a target).
- [ ] **Step 3:** Run the tests and confirm the new ones fail.
- [ ] **Step 4:** Implement.
- [ ] **Step 5:** Run the full checks and confirm they pass.
- [ ] **Step 6:** Commit `feat(alerting): richer coupon alerts with product link and offer age`.

### Task 4: Offer alerts (text, the coupon-dependent rule, retries)

RA: §4.2 (the offer-alert bullets), §4.3, §5.

**Files:**
- Modify:
  - `velkgram/alerting/domain/models.py` (`AlertMessage.title`, `AlertMessage.store_title`)
  - `velkgram/alerting/domain/format.py` (`format_alert`, `format_coupon_line`, new `extra_lines`)
  - `velkgram/alerting/services/evaluate.py`
  - `velkgram/offers/domain/title.py` and `velkgram/offers/__init__.py` (`split_title`, `store_title`)
  - `velkgram/apps/collector/collector.py` (Evaluator wiring and `build_message`)
- Test:
  - `tests/alerting/domain/test_format.py`
  - `tests/alerting/services/test_evaluate_coupons.py` and the evaluator tests
  - `tests/apps/test_collector_assembly.py`

**Interfaces:**
- **Consumes:** `ActiveCoupon.cap_cents` (Task 1); `format_saving` (Task 3).
- **Produces, in `offers/domain/title.py`, re-exported from `velkgram.offers`:**
  - `split_title(text: str, store: str | None) -> tuple[str, str]` returns `(title_of(text, store), rest)`. `rest` is the text after the title line: the first line whose `_clean` form is non-empty, the same rule `title_of` uses. When no line qualifies, `rest` is `""`.
  - `store_title(slug: str) -> str`, which returns `STORE_TITLES.get(slug, slug)`.
- **Produces `AlertMessage.title: str = ""`, `AlertMessage.body: str = ""` (the text after the title line) and `AlertMessage.store_title: str | None = None`.**
- **Produces new `Evaluator.__init__` keywords:**
  - `split_title: Callable[[str, str | None], tuple[str, str]]`. Its default splits at the first non-blank line, stripped.
  - `store_title: Callable[[str], str]`. Its default is the identity, so harness tests show the slug.
- **`_notify_and_finalize`:**
  - `store, _ = self._class_of(m)` (memoized, so no new I/O);
  - `title, body = self._split_title(m.text, store)`;
  - `store_title = self._store_title(store) if store else None`.
- **The coupon-dependent rule:** at the top of `_lookup`, `if extract_coupons(m.text): return []`. Both the coupon lines and the over-max path then skip.
- **`format_coupon_line(c: ActiveCoupon, price_cents: int) -> str`.** `price_cents` is required.
  - Text: `🎟️ Cupom ativo da loja: {codes} — {discount}{ a partir de R$ M}{, limite de R$ C}{format_saving(...)}`.
  - `_coupon_lines` passes the alert price. That code path already returns `()` when the price is None.
- **`extra_lines(body: str, codes: tuple[str, ...]) -> tuple[str, ...]`.**
  - It reads `body`, the text after the title line, which comes from `split_title`. It does no title detection of its own.
  - From those lines it drops:
    - blank lines;
    - lines that are empty once URLs are removed and ` -*•🔗` are stripped;
    - lines where `extract_price(line)` is not None;
    - lines that contain any of `codes`;
    - lines whose accent-folded, lowercased form, stripped of ` -`, equals `anuncio`.
  - Each kept line is stripped of a leading `-` and surrounding spaces.
  - At most 3 lines are kept, with a budget of 200 characters of line text (newlines don't count). The line that would pass the budget is cut to the remaining budget minus 1, plus `…`, and nothing after it is kept.
- **`format_alert` layout** (lines in braces are omitted when empty; never a blank line):
  ```
  🔔 {wish}
  {title}
  💰 {R$ price | ⚠️ preço não identificado}{ · {store_title}}{ (acima do seu limite de R$ X, mas há cupom)}
  {🎟️ Cupom no post: CODE[, CODE2]}
  {coupon_lines…}
  {⏱ atrasado N min}
  {extra lines…}
  via {channel}
  {link}
  ```
  - `rendered`, when set, is still returned verbatim.
  - The `text[:300]` dump and the price-line ` com cupom …` suffix are removed.
- **`Collector.build_message`** (the retry path): for an offer alert, `store = classify_message(m).store`. It passes `title, body = split_title(m.text, store)` and `store_title=store_title(store) if store else None`. It still sends no coupon lines.

- [ ] **Step 1: Write failing tests**
  - **Golden full post.** Wish "Monitor", channel "Promotom", store title "Mercado Livre", price 151700, text:
    ```
    Monitor Gamer LG UltraGear Curvo 34"- QuadHD 2K -34G600A

    R$ 1517
    -CUPOM: FAVORITO

    https://meli.la/2ZeTaW5

    -Anúncio
    ```
    The output is exactly:
    ```
    🔔 Monitor
    Monitor Gamer LG UltraGear Curvo 34"- QuadHD 2K -34G600A
    💰 R$ 1.517,00 · Mercado Livre
    🎟️ Cupom no post: FAVORITO
    via Promotom
    https://meli.la/2ZeTaW5
    ```
  - **Golden active coupon.** Price 151700 and `ActiveCoupon(discount="15% OFF", min_cents=None, cap_cents=4000, codes=("ESPECIALML",))` give this coupon line:
    `🎟️ Cupom ativo da loja: ESPECIALML — 15% OFF, limite de R$ 40,00 → R$ 40,00 de desconto (2,6%) → ~R$ 1.477,00 ⚠️ limite baixo`
  - **Other cases** (each its own test):
    - no price → `💰 ⚠️ preço não identificado · Mercado Livre`;
    - unknown store → no ` · `;
    - over max with price 151700 and max 140000 → the 💰 line ends ` (acima do seu limite de R$ 1.400,00, mas há cupom)`;
    - delayed 7 → `⏱ atrasado 7 min` just before the extra lines;
    - an empty title → no title line.
  - **`extra_lines`:**
    - "Resgate cupom do anúncio" is kept;
    - title + price + link only → `()`;
    - 5 candidate lines → 3;
    - one 300-character line → one line of 200 characters ending `…`;
    - two 150-character lines → the first whole, the second cut to 49 characters + `…`;
    - `split_title("🔥🔥🔥\nMonitor X\nDetalhe", None)` returns `("Monitor X", "Detalhe")`, so the extras are exactly `("Detalhe",)`.
  - **Evaluator:**
    - a post with "-CUPOM: X" makes no `for_store` call, creates no over-max alert even with an active coupon, and still alerts within max;
    - `AlertMessage` carries `title`, `body` and `store_title` from the injected callables.
  - **Collector:** a failed offer alert that is retried through `build_message` has the title line and ` · <store>` in its text.
- [ ] **Step 2: Rewrite the existing tests that pin the old text.**
  - `tests/alerting/domain/test_format.py`: the `"y"*300` dump test, `test_alert_mentions_the_coupon_right_after_the_price`, `test_alert_lists_several_coupons`, `test_alert_without_a_coupon_keeps_the_plain_price_line` (line 1 is now the title), and the one-argument `format_coupon_line(c)` calls (lines ~140–170).
  - `tests/alerting/services/test_evaluate_coupons.py:~160`: the exact coupon-line strings now carry the saving suffix.
- [ ] **Step 3:** Run the tests and confirm the new ones fail.
- [ ] **Step 4:** Implement.
- [ ] **Step 5:** Run the full checks and confirm they pass.
- [ ] **Step 6:** Commit `feat(alerting): richer offer alerts and skip store coupons for coupon-dependent posts`.

---

## Execution notes (controller)
- **Order:** 1 → 2 → 3 → 4. Task 3 needs Tasks 1 and 2; Task 4 needs Tasks 1 and 3.
- **Deploy (owner):**
  1. `docker compose build && docker compose up -d`.
  2. `docker compose run --rm migrate velkgram rebuild-offers` (RA §6).
  3. Confirm the enricher is running.
- **Real check (RA §7):** one GET per built store URL, except Mercado Livre, which the owner confirmed. Then the owner reads one real offer alert and one real coupon alert.
