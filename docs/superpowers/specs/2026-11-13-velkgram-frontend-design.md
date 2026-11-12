# Velkgram front end: refine, then islands

Status: proposed. Decision with the owner on 2026-11-13: **refine the current front end and add
small interactive islands where they pay off**, not a rewrite as a single-page app. Priorities:
a consistent, polished look, and a fast feed. Not priorities: installable PWA, offline, web push.

## What exists (audit)

- 29 Jinja templates (901 lines), one stylesheet (`velkgram.css`, 1,564 lines), one script
  (`velkgram.js`, 144 lines), HTMX for partial updates.
- Loaded from outside the app on every page: Google Fonts (Roboto Flex and the icon font), Beer
  CSS 5.0.3 (stylesheet and script) from jsDelivr, HTMX 2.0.3 from unpkg.
- Beer CSS is used lightly: about ten component types (`button`, `chip`, `field` with a floating
  label, `circle`, `tonal`, `transparent`, `border`, `small`, `row`) plus its JS for five toggles
  (`data-ui`: the theme menu, the channel row menu, the filters sheet). The themes already define
  Material 3 colour tokens in our own CSS.
- The feed already filters live: the form uses `hx-get` with `change` and a 400 ms `input`
  trigger, `hx-push-url` and `hx-sync="this:replace"`. So "fast feed" is mostly about how the
  swap feels (no flash, no lost scroll, instant feedback), not about a client-side framework.

## Why not a single-page app

~15 screens would be rewritten, plus a JSON API with the authorization rules built for multi-user,
a Node build in Docker and CI, and new test layers. The gains (offline, push, rich real-time) are
not wanted. The weaknesses are consistency and finish, which a framework does not fix by itself.

## Goals

1. One design system: tokens (colour, space, radius, type, elevation) and a small set of
   components with one way to build each. No `!important` fights with a third-party stylesheet.
2. No third-party stylesheet or script: fonts, icons and HTMX served by the app.
3. Native platform features instead of library JS: `popover` for menus, `<dialog>` for the filters
   sheet, `@view-transition` and `:has()` for state, `scroll-snap`, `content-visibility`.
4. A feed that feels instant: the swap keeps scroll and focus, shows progress, and the cards
   appear without a flash.
5. Islands only where HTMX cannot do the job: chart tooltips on hover or touch, and later the
   store comparison. Preact and `htm` as vendored ES modules, no build step.
6. A repeatable visual check, so "looks consistent" is measured: overflow, tap target size and
   alignment at 320 to 1440 px in every theme.

## Design system

- **Tokens** (`:root`, overridden by the theme classes): the existing Material 3 colour roles,
  plus a spacing scale (4, 8, 12, 16, 24, 32, 48 px), a type scale (12, 14, 16, 20, 24, 32), radii
  (8, 12, 16, pill) and two elevations.
- **Components** (prefix `vg-`): button (filled, tonal, outlined, text, icon), chip, field (input,
  select, textarea with a label), card, list row, app bar, navigation (rail and bottom bar),
  menu (popover), sheet (dialog), tabs (segmented), banner, empty state, table, stat block.
- **Layout primitives:** stack, cluster, grid with `auto-fill` and container queries for cards.
- **Coexistence while migrating:** new components use `vg-` classes and live beside Beer CSS; a
  screen is migrated whole, its tests updated, and Beer is removed when no template uses it.

## Stages (each ends green and committed)

1. **Safety net and foundations:** the UI audit script and a baseline; tokens and the component
   stylesheet split into files and served as one bundle with a content hash; HTMX, fonts and
   icons self-hosted.
2. **Shell:** app bar, navigation, menus (popover), theme menu, login. Remove Beer JS.
3. **Screens:** feed (cards, filters sheet, empty and loading states), product page and comparison,
   wishes, alerts, channels, status, users, profile. One screen per commit.
4. **Feed feel:** view transitions on swaps, preload on hover, scroll and focus kept, a skeleton
   for the first load, instant optimistic state for the follow button.
5. **Islands:** chart tooltips (Preact + htm), then comparison if it earns it.
6. **Remove Beer CSS** and the remaining external requests; update the README.

## Risks

- Many tests assert Beer class names in the HTML; they change with each screen, so each screen's
  migration includes its tests.
- Dropping the icon font for an SVG sprite saves weight but needs the icons we use extracted once;
  until then the font is self-hosted and subset.
- Native `popover` and view transitions need a current browser; both degrade to a plain page.

## Visual direction (design pass with the frontend-design guidance)

### The subject

A private tool for Brazilian deal hunting: Telegram promo channels reduced to the few offers that
matter to a handful of people. It is read quickly, mostly on a phone, and the one question asked
a hundred times is "is this a good price?". The vernacular is the price tag, the coupon, the
shelf label, the receipt: printed, numeric, practical.

### Plan (first pass)

- **Colour:** the owner chose the themes (Catppuccin flavours and the Gruvbox "bem pastel" pair),
  and the brief wins, so the palette is the existing role tokens. Reference, Gruvbox dark:
  paper `#282828`, ink `#d4be98`, stamp (primary) `#bab979`, amber (coupons) `#d6b071`,
  sage `#a0b49f`, coral (price above average) `#e18b78`. Store colours stay as brand inks.
- **Type:** one family, Bricolage Grotesque (variable: optical size 12 to 96, weight 200 to 800,
  width 75 to 100), self-hosted. Body: opsz 14, width 100, weight 400. Titles: opsz 28,
  weight 600. **Prices: width 75 (condensed), weight 800, tabular lining numerals**, sized by
  importance. Sentence case everywhere; no all-caps labels.
- **Layout:** the feed is a ruled list, not boxed cards: a row per offer with the price in a
  fixed left rail, so prices line up down the screen and can be compared by eye.
  Coupons are the exception: perforated tickets with the code on a tear-off stub.
- **Principles:** price first; structure carries information (a rule separates offers, the rail
  aligns prices, the notch marks a coupon); one memorable element (the ticket); calm elsewhere;
  motion only as an answer to an action (a swap, an open sheet).

```
 offer row (phone)                      coupon ticket
 ┌──────────────────────────────┐       ╭──────────────────┬─ ─ ─╮
 │ R$ 884   Monitor TCL 25G64   │       │ R$ 20 de desconto│ CODE│
 │ −12%     KaBuM!  Promotom 2h │       │ em compras de R$ │ BF20│
 │ abaixo   Também em 3 lojas   │       ╰──────────────────┴─ ─ ─╯
 ├──────────────────────────────┤        notch circles at the perforation
 │ R$ 1.199 Teclado ...         │
 └──────────────────────────────┘
```

### Review against the defaults (second pass)

Things the first idea shared with a generic deal-site template, and what changed:

- *Boxed rounded cards with one radius and one soft shadow* (the SaaS card kit): replaced by
  ruled rows. Radii are chosen by role (small for chips and stamps, larger for sheets, circles for
  the ticket notches) instead of one value everywhere.
- *Monospace for small data labels, all-caps eyebrows, "A · B · C" meta strings, "→" on buttons:*
  none. The existing middle-dot strings ("menor R$ 884 em 10/11 · 9 ofertas") become structured
  fields with their own labels. Labels are sentence case.
- *Roboto Flex* is the Material default: replaced by a family with a point of view and a
  condensed width that suits prices.
- *Colour:* kept on purpose, because the owner picked these themes. No warm-cream-and-terracotta,
  no acid accent, no gradients.
- *Copy:* two buttons are ambiguous today ("Produto" opens the store page, "Abrir" opens the
  Telegram post). They become "Ver na loja" and "Ver no Telegram", used the same way everywhere.

### Quality floor

Visible keyboard focus, `prefers-reduced-motion` respected, contrast checked per theme (the test
suite already enforces WCAG AA for the flavours), tap targets of 40 px or more, the UI audit
script clean at 320 to 1440 px.
