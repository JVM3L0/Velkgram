-- Coupon data on offers. SQL only knows the title rule for `kind`; `velkgram rebuild-offers`
-- fills codes, discount, minimum spend, scope and links from the stored posts.
ALTER TABLE offers ADD COLUMN kind TEXT NOT NULL DEFAULT 'product';
ALTER TABLE offers ADD COLUMN coupons TEXT;
ALTER TABLE offers ADD COLUMN coupon_discount TEXT;
ALTER TABLE offers ADD COLUMN coupon_min_cents INTEGER;
ALTER TABLE offers ADD COLUMN coupon_scope TEXT;
ALTER TABLE offers ADD COLUMN redeem_link TEXT;
ALTER TABLE offers ADD COLUMN cart_link TEXT;
ALTER TABLE offers ADD COLUMN coupon_tiers TEXT;  -- JSON [[discount, min_cents], ...]

UPDATE offers SET kind = 'coupon', price_cents = NULL, comparable = 0
WHERE title LIKE 'cupom%';

CREATE INDEX idx_offers_kind_posted_at ON offers (kind, posted_at DESC);
