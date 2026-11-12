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

## Visual direction (decided with the owner, 2026-11-13)

The first proposal was a distinct "price tag" identity (condensed prices in a ruled list, coupons
as perforated tickets). The owner chose differently, and the brief wins:

- **Identity: evolve the current look.** Cards stay as they are; the work is consistency and
  finish (tokens, spacing, components), not a new personality.
- **Themes: two**, a dark and a light, designed together with the Gruvbox "bem pastel" pair as
  the base. The Catppuccin flavours go away. Modes in the menu: Sistema, Escuro, Claro. An old
  `theme` cookie value maps to the nearest of the two (mocha, macchiato, frappe and gruvbox-dark
  to dark; latte and gruvbox-light to light).
- **Feed: cards as today** (the cards and list views both stay).
- **Type: Bricolage Grotesque**, one self-hosted family (optical size 12 to 96, weight 200 to
  800, width 75 to 100). Body at width 100; prices in a heavier, slightly condensed setting with
  tabular lining numerals so the digits line up between cards. Sentence case; no all-caps labels.

### Quality floor

Visible keyboard focus, `prefers-reduced-motion` respected, contrast checked per theme (the test
suite enforces WCAG AA), tap targets of 40 px or more, and the UI audit script clean at 320 to
1440 px. Copy: "Produto" and "Abrir" are ambiguous today (the store page and the Telegram post);
they become "Ver na loja" and "Ver no Telegram", the same way everywhere.

### Stages that follow from this (replaces the earlier list for the visual work)

1. Typography: self-hosted font, type scale tokens, price style. No third-party font request.
2. Themes: reduce to Escuro and Claro, migrate old cookie values, drop the Catppuccin CSS and its
   tests. Redesign the two palettes together so roles (surface levels, accents, store inks) agree.
3. Components: one definition each of button, chip, field, card, list row; remove duplicated and
   `!important` rules; migrate screens one at a time with the UI audit as the check.
4. Shell without Beer JS (native `popover` and `<dialog>`), then self-host HTMX and remove Beer CSS.
5. Feed feel and the chart-tooltip island, as in the earlier plan.
