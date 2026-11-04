CREATE TABLE alerts (
    id INTEGER PRIMARY KEY,
    wish_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    price_cents INTEGER,
    price_unknown INTEGER NOT NULL,
    dedup_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed', 'expired')),
    attempts INTEGER NOT NULL,
    delayed_minutes INTEGER,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    latency_telegram_ms INTEGER NOT NULL,
    latency_internal_ms INTEGER NOT NULL,
    last_error TEXT
);

CREATE INDEX idx_alerts_created_at ON alerts (created_at);
CREATE INDEX idx_alerts_status_created_at ON alerts (status, created_at);
CREATE INDEX idx_alerts_message ON alerts (channel_id, message_id);

CREATE TABLE alert_suppressions (
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    wish_id INTEGER NOT NULL,
    rule TEXT NOT NULL CHECK (rule IN ('origin', 'wish_price', 'wish_text')),
    matched_alert_id INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_alert_suppressions_created_at ON alert_suppressions (created_at);
