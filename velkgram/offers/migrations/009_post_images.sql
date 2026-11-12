-- Image URL of a Telegram post, read from the public web view of its channel (t.me/s/<name>).
-- The CDN URL is public, so no file is stored. Owned by offers; pruned with the offers.
CREATE TABLE IF NOT EXISTS post_images (
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (channel_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_post_images_fetched_at ON post_images (fetched_at);
