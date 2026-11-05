CREATE TABLE wishes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    required_terms TEXT NOT NULL,
    excluded_terms TEXT NOT NULL,
    max_price_cents INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
