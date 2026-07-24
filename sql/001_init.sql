-- =============================================================
-- 001_init.sql — Core schema (Day 2 + Day 5 + Day 8)
--   Documents, Chunks, API keys, Request logs
-- =============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Enable pgvector (Day 4)
CREATE EXTENSION IF NOT EXISTS vector;

-- -----------------------------
-- documents: metadata + status
-- -----------------------------
CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source          TEXT NOT NULL,                    -- e.g. "ingest_api"
    content_type    TEXT NOT NULL DEFAULT 'application/json',
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','processing','crushed','embedded','failed')),
    minio_object    TEXT NOT NULL,                    -- s3://bucket/key
    raw_sha256      TEXT,                             -- SHA256 of raw text
    crushed_sha256  TEXT,
    error           TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_status      ON documents (status);
CREATE INDEX IF NOT EXISTS idx_documents_created_at  ON documents (created_at DESC);

-- -----------------------------
-- chunks: crushed text + vector (Day 4 + Day 11)
-- -----------------------------
CREATE TABLE IF NOT EXISTS chunks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    raw_text        TEXT NOT NULL,                    -- crushed text (CCR compressed)
    raw_text_len    INTEGER NOT NULL DEFAULT 0,
    original_text   TEXT,                             -- pre-crush original (for CCR reversal)
    original_len    INTEGER NOT NULL DEFAULT 0,
    embedding       vector(1536),                    -- pgvector (Day 4)
    model           TEXT,
    tokens          INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks (document_id);

-- -----------------------------
-- api_keys: hashed keys (Day 8)
-- -----------------------------
CREATE TABLE IF NOT EXISTS api_keys (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL,
    key_hash        TEXT NOT NULL UNIQUE,             -- SHA256 of the raw key
    key_prefix      TEXT NOT NULL,                    -- first 8 chars, for UI
    name            TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys (key_hash) WHERE is_active = TRUE;

-- -----------------------------
-- request_logs: cost tracking (Day 5)
-- -----------------------------
CREATE TABLE IF NOT EXISTS request_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    api_key_id      UUID REFERENCES api_keys(id) ON DELETE SET NULL,
    user_id         UUID,
    endpoint        TEXT NOT NULL,
    method          TEXT NOT NULL,
    status_code     INTEGER NOT NULL,
    cache_hit       BOOLEAN NOT NULL DEFAULT FALSE,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(10,6) NOT NULL DEFAULT 0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    request_id      TEXT,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_request_logs_created_at ON request_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_request_logs_api_key    ON request_logs (api_key_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_request_logs_cache_hit  ON request_logs (cache_hit) WHERE cache_hit = TRUE;

-- -----------------------------
-- updated_at trigger
-- -----------------------------
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_documents_touch ON documents;
CREATE TRIGGER trg_documents_touch BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
