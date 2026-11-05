CREATE TABLE offers (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    posted_at TEXT NOT NULL,
    title TEXT NOT NULL,
    price_cents INTEGER,
    store TEXT,
    main_link TEXT,
    has_photo INTEGER NOT NULL,
    text TEXT,
    norm_text TEXT,
    origin_channel_id INTEGER,
    origin_message_id INTEGER,
    sold_out INTEGER NOT NULL,
    deleted INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (channel_id, message_id)
);

CREATE INDEX idx_offers_posted_at ON offers (posted_at DESC);
CREATE INDEX idx_offers_store_posted_at ON offers (store, posted_at);
CREATE INDEX idx_offers_origin ON offers (origin_channel_id, origin_message_id);

CREATE VIRTUAL TABLE offers_fts USING fts5(
    title, text, content='offers', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER offers_ai AFTER INSERT ON offers WHEN new.text IS NOT NULL BEGIN
    INSERT INTO offers_fts (rowid, title, text) VALUES (new.id, new.title, new.text);
END;

CREATE TRIGGER offers_ad AFTER DELETE ON offers WHEN old.text IS NOT NULL BEGIN
    INSERT INTO offers_fts (offers_fts, rowid, title, text)
    VALUES ('delete', old.id, old.title, old.text);
END;

CREATE TRIGGER offers_au AFTER UPDATE OF title, text ON offers BEGIN
    INSERT INTO offers_fts (offers_fts, rowid, title, text)
    SELECT 'delete', old.id, old.title, old.text WHERE old.text IS NOT NULL;
    INSERT INTO offers_fts (rowid, title, text)
    SELECT new.id, new.title, new.text WHERE new.text IS NOT NULL;
END;

CREATE TABLE offer_matches (
    wish_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    price_cents INTEGER,
    posted_at TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('live', 'retro')),
    matched_at TEXT NOT NULL,
    PRIMARY KEY (wish_id, channel_id, message_id)
);

CREATE INDEX idx_offer_matches_wish_posted ON offer_matches (wish_id, posted_at);

CREATE TABLE retro_runs (
    wish_id INTEGER PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT
);
