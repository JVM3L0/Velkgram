-- The price a store page states for the product (cents), read by the link enricher off the alert
-- path. NULL: not read, or the page was unclear.
ALTER TABLE product_links ADD COLUMN page_price_cents INTEGER;
