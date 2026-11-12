-- Model codes of each product offer (AOC U34G4C, Asus VG27AQME5F...), the key for finding the same
-- product in other stores. Filled when an offer is stored; `velkgram rebuild-offers` fills the
-- offers that already exist.
CREATE TABLE IF NOT EXISTS offer_codes (
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    PRIMARY KEY (channel_id, message_id, code)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_offer_codes_code ON offer_codes (code);
