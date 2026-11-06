-- Link enrichment: one row per distinct offers.main_link (joined by equal strings).
CREATE TABLE product_links (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    final_url TEXT,
    store TEXT,
    product_id TEXT,
    title TEXT,
    image_url TEXT,
    kind TEXT NOT NULL DEFAULT 'unknown' CHECK (kind IN ('product', 'not_product', 'unknown')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'done', 'failed', 'blocked')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_try_at TEXT,
    fetched_at TEXT,
    created_at TEXT NOT NULL,
    offer_posted_at TEXT NOT NULL,
    host TEXT NOT NULL,
    final_host TEXT,
    blocks INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_product_links_status_next ON product_links (status, next_try_at);
CREATE INDEX idx_product_links_offer_posted_at ON product_links (offer_posted_at);
CREATE INDEX idx_product_links_store_product ON product_links (store, product_id);
CREATE INDEX idx_offers_main_link ON offers (main_link);

CREATE TABLE link_enrich_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_run_at TEXT,
    pending INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    blocked INTEGER NOT NULL DEFAULT 0
);
