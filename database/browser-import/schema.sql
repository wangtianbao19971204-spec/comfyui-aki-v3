-- Contract only. The reviewed application owns creation and future migration.
-- Actual mutable database and prompts stay outside Git.
CREATE TABLE inbox (
    import_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    receiver_id TEXT,
    claim_token TEXT,
    claim_expires_at REAL
);
CREATE TABLE accepted (
    import_id TEXT PRIMARY KEY,
    receiver_id TEXT NOT NULL,
    claim_token TEXT NOT NULL,
    accepted_at REAL NOT NULL
);
CREATE TABLE state (
    id INTEGER PRIMARY KEY CHECK(id=1),
    payload_json TEXT NOT NULL,
    received_at_ns INTEGER NOT NULL
);
PRAGMA user_version=1;
