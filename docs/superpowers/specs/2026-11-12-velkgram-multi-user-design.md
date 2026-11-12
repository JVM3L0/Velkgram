# Velkgram multi-user design

Status: implemented (stages 1 to 5). Decisions taken with the owner on 2026-11-12:

- **Audience:** a few trusted people (2 to 10). Accounts are created by the owner. No open signup.
- **Channels:** global. One list of Telegram channels and one collector session, both the owner's.
- **Alerts:** one shared bot; each user receives alerts in their own chat.
- **Login:** username and password, created by the owner.

## Goals and non-goals

Goals: each user has their own wishes, their own alerts and their own notification chat, and cannot
see or change anyone else's. Offers, channels, the collector and the enricher stay shared, so every
post is collected and enriched once.

Non-goals: open signup, e-mail, password recovery by e-mail, 2FA, per-user channels, per-user bots,
quotas, billing.

## What is shared and what is per user

| Data | Scope |
|---|---|
| channels, messages, offers, product links, post images, coupons seen in posts | shared |
| wishes, offer matches, retro runs, alerts, suppressions | per user (through the wish) |
| Telegram chat id for alerts, theme choice | per user |
| notifier status, collector heartbeat, channel admin, user admin | admin only |

Wishes already isolate matches, alerts and dedup (every key carries `wish_id`), so the data model
change is small: a `users` table and an owner on each wish.

## Data model

New module `accounts` (hexagonal, like the others, with its own migrations):

```
users(
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,          -- scrypt, same format as today; '' = cannot log in yet
  role TEXT NOT NULL CHECK (role IN ('admin','user')),
  telegram_chat_id INTEGER,             -- NULL until the user sets it
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
)
```

- Migration inserts user `1`, `admin`, role `admin`, empty password hash.
- `wishes.user_id INTEGER NOT NULL DEFAULT 1` (existing wishes belong to the admin).
- Bootstrap at web and collector start: if the admin hash is empty and `WEB_PASSWORD_HASH` is set,
  copy it in; if the admin chat id is empty and `ALERT_CHAT_ID` is set, copy that too. The current
  single-password login keeps working as the `admin` user with no change for the owner.

## Authentication

- `POST /login` takes `username` and `password`. The session stores `user_id`; each request loads the
  user, and a disabled or deleted user is logged out.
- `require_user` returns the current user; `require_admin` returns it only for role `admin`
  (HTTP 403 otherwise).
- Login throttle: per username (5 failures in 15 min lock it for 5 min) plus a global cap, so the
  throttle cannot be used to enumerate usernames. Same message for an unknown user and a wrong password.
- Passwords use the existing scrypt helper. The CLI and the admin page generate or set them.
- `same_site="strict"` and `WEB_HTTPS_ONLY` stay as they are.

## Authorization

Every route that takes a `wish_id` checks `wish.user_id == current_user.id` and answers 404 (not 403)
otherwise, so ids cannot be probed. This covers the wishlist routes and the offers routes under
`/wishes/{wish_id}` (product page, matches, chart, history, retry). The alerts page lists only alerts
of the user's wishes. Channels, status and users pages require admin.

Module boundaries: modules never join each other's tables. The web layer passes the current user's
wish ids to `AlertQueries` and `OfferQueries`; `wishlist` exposes `list_for_user(user_id)` in its
public API.

## Alert delivery

- `WishView` (shared, plain data) gains `user_id`.
- `AlertMessage` gains `chat_id: int | None`, resolved when the alert is sent through a new
  alerting port `ChatDirectory.chat_id(user_id)`, whose adapter calls the `accounts` public API.
- `Notifier.send(message)` sends to `message.chat_id`. When it is `None` the alert is stored as
  `failed` with the reason "Telegram não configurado", visible on the user's alerts page, and is not
  retried until the user sets a chat id.
- `notify_system` (collector failures, login lost) goes to the admin chat.
- Dedup keys already contain `wish_id`, so two users with similar wishes each get their own alert.
- Each user must open the bot and press Start once (Telegram rule). The chat id is the user's numeric
  Telegram id, which the user reads from `@userinfobot` and saves on the profile page. A `/start`
  deep link that fills it automatically is a later improvement, not part of the first version.

## Pages

- `/login` gains the username field.
- `/perfil` (every user): change password, Telegram id, "send test alert", theme.
- `/usuarios` (admin): list, create (shows a generated password once), reset password,
  enable or disable, set a chat id.
- `/canais` and `/status` become admin only; the menu hides them for other users.
- Feed, coupons and offer pages stay open to every logged user. "Acompanhar" creates the wish for the
  current user.

## CLI

`velkgram user add <name> [--admin]`, `velkgram user passwd <name>`, `velkgram user disable <name>`,
`velkgram user list`. They run against the same database, so the owner can create users from the
Railway shell without the web.

## Risks

- **Authorization gaps (IDOR).** Mitigation: one shared dependency that loads a wish by id for the
  current user, used by every route, plus a test per route that another user gets 404.
- **Chat id mistakes.** A wrong id sends alerts to a stranger. Mitigation: the "send test alert"
  button, and only the owner of the account or the admin can set it.
- **Data migration.** Existing wishes keep working because `user_id` defaults to the admin.
  Mitigation: migration test on a populated database.
- **Shared limits.** One bot and one Telegram account serve everyone; the alert sender already spaces
  messages (`MIN_INTERVAL_S`). With a handful of users this is enough.

## Delivery plan (each stage ends green and committed)

1. **accounts module:** domain, `users` table and migration (with the admin row and `wishes.user_id`),
   repository with its contract suite and fake, password helpers moved or shared, import-linter contracts.
2. **Authentication:** username and password login, session with `user_id`, `require_user` and
   `require_admin`, throttle per username, admin bootstrap from the environment, CLI `user` commands.
3. **Wish ownership:** `Wish.user_id`, `list_for_user`, wishlist and offers routes scoped to the user
   with 404 on someone else's wish, "Acompanhar" for the current user, tests per route.
4. **Alerts per user:** `WishView.user_id`, `ChatDirectory`, per-message chat id in the notifier, alerts
   page and queries scoped to the user's wishes, `notify_system` to the admin, tests with two users.
5. **Pages:** `/perfil`, `/usuarios`, admin-only channels and status, menu by role, test alert button.
6. **Deploy notes:** README section, Railway steps, how to create the first extra user.

Stages 1 and 2 are invisible to the single owner; the app keeps working with the same password. Users
other than the admin can only be created from stage 2 on.
