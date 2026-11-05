-- Feed filter that the kind/store feed indexes cannot serve: one channel.
-- channel_id is an equality term, so (posted_at, message_id) below it still gives the page order.
CREATE INDEX idx_offers_kind_channel_feed
    ON offers (kind, channel_id, posted_at DESC, message_id DESC);
