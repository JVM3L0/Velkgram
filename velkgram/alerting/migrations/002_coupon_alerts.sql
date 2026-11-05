ALTER TABLE alerts ADD COLUMN kind TEXT NOT NULL DEFAULT 'offer' CHECK (kind IN ('offer', 'coupon'));
ALTER TABLE alerts ADD COLUMN over_max INTEGER NOT NULL DEFAULT 0;
ALTER TABLE alerts ADD COLUMN offer_channel_id INTEGER;
ALTER TABLE alerts ADD COLUMN offer_message_id INTEGER;
ALTER TABLE alerts ADD COLUMN payload TEXT;

CREATE TABLE alert_suppressions_new (
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    wish_id INTEGER NOT NULL,
    rule TEXT NOT NULL CHECK (rule IN ('origin', 'wish_price', 'wish_text', 'wish_coupon')),
    matched_alert_id INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO alert_suppressions_new
    SELECT channel_id, message_id, wish_id, rule, matched_alert_id, created_at
    FROM alert_suppressions;

DROP TABLE alert_suppressions;
ALTER TABLE alert_suppressions_new RENAME TO alert_suppressions;
CREATE INDEX idx_alert_suppressions_created_at ON alert_suppressions (created_at);
