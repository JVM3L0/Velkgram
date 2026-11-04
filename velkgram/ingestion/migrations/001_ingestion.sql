CREATE TABLE messages (
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    received_at TEXT NOT NULL,
    text TEXT NOT NULL,
    links TEXT NOT NULL,
    fwd_from_channel_id INTEGER,
    fwd_from_message_id INTEGER,
    grouped_id INTEGER,
    has_photo INTEGER NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('live', 'backfill')),
    deleted_at TEXT,
    processed_at TEXT,
    PRIMARY KEY (channel_id, message_id)
);

CREATE INDEX idx_messages_received_at ON messages (received_at);
CREATE INDEX idx_messages_date ON messages (date);

CREATE TABLE message_versions (
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    edited_at TEXT NOT NULL,
    text TEXT NOT NULL,
    links TEXT NOT NULL,
    sold_out_hint INTEGER NOT NULL,
    PRIMARY KEY (channel_id, message_id, version)
);

CREATE TABLE ingestion_cursors (
    channel_id INTEGER PRIMARY KEY,
    last_message_id INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE collector_heartbeat (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_seen TEXT NOT NULL,
    connection_state TEXT NOT NULL CHECK (connection_state IN ('connected', 'reconnecting', 'fatal')),
    fatal_reason TEXT,
    messages_seen INTEGER NOT NULL,
    alerts_sent INTEGER NOT NULL
);
