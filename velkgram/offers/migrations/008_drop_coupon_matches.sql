-- Coupon posts list many products, so their text matched wishes by accident. They are no
-- longer matched (see OfferBuilder); drop the history rows already stored for them.
DELETE FROM offer_matches
WHERE EXISTS (
    SELECT 1 FROM offers o
    WHERE o.channel_id = offer_matches.channel_id
      AND o.message_id = offer_matches.message_id
      AND o.kind = 'coupon'
);
