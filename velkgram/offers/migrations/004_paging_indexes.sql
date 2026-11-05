-- Keyset paging orders by (posted_at, channel_id, message_id): put all three in the index, so a
-- page is a range read with no sort even when many rows share one posted_at.
CREATE INDEX idx_offers_kind_feed ON offers (kind, posted_at DESC, channel_id DESC, message_id DESC);
DROP INDEX idx_offers_kind_posted_at;

-- Same for a coupon or product list filtered by store (feed store filter, coupons page).
CREATE INDEX idx_offers_store_kind_feed
    ON offers (store, kind, posted_at DESC, channel_id DESC, message_id DESC);

CREATE INDEX idx_offer_matches_wish_feed
    ON offer_matches (wish_id, posted_at DESC, channel_id DESC, message_id DESC);
DROP INDEX idx_offer_matches_wish_posted;
