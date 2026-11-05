CREATE TABLE state_versions (
    name TEXT PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 0
);

INSERT INTO state_versions (name, version) VALUES ('wishlist', 0), ('channels', 0);
