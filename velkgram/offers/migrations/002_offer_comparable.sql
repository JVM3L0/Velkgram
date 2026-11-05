-- Coupons and multi-price posts are excluded from price charts and stats.
-- SQL only knows the title rule; `velkgram rebuild-offers` recomputes the rest.
ALTER TABLE offers ADD COLUMN comparable INTEGER NOT NULL DEFAULT 1;

UPDATE offers SET comparable = 0 WHERE title LIKE 'cupom%' OR title LIKE 'cúpom%';
