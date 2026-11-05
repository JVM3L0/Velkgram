CREATE TABLE channels (
    id INTEGER PRIMARY KEY,
    ref TEXT NOT NULL UNIQUE,
    telegram_id INTEGER UNIQUE,
    name TEXT,
    status TEXT NOT NULL,
    error TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    silent_after_hours INTEGER NOT NULL DEFAULT 12,
    created_at TEXT NOT NULL
);
