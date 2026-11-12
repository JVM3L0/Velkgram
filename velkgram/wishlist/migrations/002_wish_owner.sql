-- Every wish has an owner; existing wishes belong to user 1 (the admin, see accounts).
ALTER TABLE wishes ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1;
CREATE INDEX idx_wishes_user ON wishes (user_id);
