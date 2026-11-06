-- Dominant-product counting walks every match of a wish and joins its offer and link. These two
-- covering indexes answer the walk from the index alone (no offers/offer_matches row fetches).
CREATE INDEX idx_offer_matches_wish_cover
    ON offer_matches (wish_id, channel_id, message_id, price_cents);
CREATE INDEX idx_offers_key_cover ON offers (channel_id, message_id, comparable, main_link);
