-- =============================================================
-- 002_indexes.sql — HNSW vector index (Day 11)
--   Run AFTER seeding 100k vectors (see scripts/seed_vectors.py)
--   Before:  Seq Scan, ~400ms over 100k rows
--   After:   HNSW index scan, ~2ms over 100k rows (m=16, ef_construction=64)
-- =============================================================

-- Drop if exists to allow re-tuning
DROP INDEX IF EXISTS idx_chunks_embedding_hnsw;

-- HNSW = Hierarchical Navigable Small World graph
--   m                  — max graph connections per node (16 default, ~memory vs recall)
--   ef_construction    — build-time search width (64 default, higher = better recall, slower build)
--   vector_cosine_ops  — operator class for cosine distance (<=>)
CREATE INDEX idx_chunks_embedding_hnsw
    ON chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- For exact-match chunk lookups (CCR tool calls)
CREATE INDEX IF NOT EXISTS idx_chunks_id_lookup ON chunks (id);
