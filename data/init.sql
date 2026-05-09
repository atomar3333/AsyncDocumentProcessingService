PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE jobs (
    id              TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    document_url    TEXT NOT NULL,
    analysis_type   TEXT NOT NULL CHECK (analysis_type IN ('summary', 'extraction', 'classification')),
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'fetching', 'processing', 'validating', 'completed', 'failed')),
    result          TEXT,          -- JSON blob
    error           TEXT,          -- JSON blob
    token_usage     TEXT,          -- JSON blob: {"input_tokens": N, "output_tokens": N, "total_tokens": N}
    token_budget    INTEGER NOT NULL DEFAULT 4096,
    metadata        TEXT,          -- JSON blob
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at    TEXT
);
CREATE TABLE audit_trail (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL REFERENCES jobs(id),
    from_state  TEXT,
    to_state    TEXT NOT NULL CHECK (to_state IN ('pending', 'fetching', 'processing', 'validating', 'completed', 'failed')),
    reason      TEXT,
    timestamp   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TRIGGER trg_jobs_updated_at
AFTER UPDATE ON jobs
BEGIN
    UPDATE jobs SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id;
END;
CREATE INDEX idx_jobs_idempotency_key ON jobs(idempotency_key);
CREATE INDEX idx_jobs_status           ON jobs(status);
CREATE INDEX idx_jobs_created_at       ON jobs(created_at);
CREATE INDEX idx_audit_trail_job_id ON audit_trail(job_id);
COMMIT;
