CREATE TABLE IF NOT EXISTS notifier_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT NOT NULL CHECK (status IN ('ok', 'needs_start', 'error', 'disabled')),
    detail TEXT,
    chat_id INTEGER,
    updated_at TEXT NOT NULL
);
