CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    telegram_chat_id INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- The owner's account: existing wishes already belong to user 1. The password comes from
-- WEB_PASSWORD_HASH at start-up (see accounts.ensure_admin); until then it cannot log in.
INSERT INTO users (id, username, password_hash, role, telegram_chat_id, enabled, created_at)
VALUES (1, 'admin', '', 'admin', NULL, 1, strftime('%Y-%m-%dT%H:%M:%S.000000Z', 'now'));
