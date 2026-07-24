"""
Day 11 deliverable — seed 100k random vectors and run EXPLAIN ANALYZE.

Before HNSW index: Seq Scan, ~400ms
After  HNSW index:  Index Scan, ~2ms

Run:
    python scripts/seed_vectors.py seed      # inserts 100k rows
    python scripts/seed_vectors.py bench     # runs EXPLAIN ANALYZE before/after index

Note: real embeddings are 1536-dim. For benchmarking we use random vectors
since the query planner behavior is identical.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import time

# Allow running as a script (not a package) — must come before app.* imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import close_pool, init_pool  # noqa: E402
from app.logging_config import configure_logging, get_logger  # noqa: E402


async def seed(count: int = 100_000, batch_size: int = 1000) -> None:
    configure_logging()
    log = get_logger("seed_vectors")
    pool = await init_pool()
    try:
        # Need a parent document for FK
        async with pool.acquire() as conn:
            doc_id = await conn.fetchval("""
                INSERT INTO documents (source, content_type, size_bytes, status, minio_object)
                VALUES ('seed', 'application/json', 0, 'embedded', 's3://seed/seed.json')
                RETURNING id
                """)

        log.info("seeding_start", count=count, batch_size=batch_size, doc_id=str(doc_id))
        started = time.time()

        rng = random.Random(42)
        for batch_start in range(0, count, batch_size):
            rows = []
            for i in range(batch_size):
                # Random 1536-dim unit vector (approx via gaussian + normalize)
                vec = [rng.gauss(0, 1) for _ in range(1536)]
                norm = sum(x * x for x in vec) ** 0.5 or 1.0
                vec = [x / norm for x in vec]
                rows.append((doc_id, batch_start + i, f"chunk-{batch_start + i}", 0, str(vec)))

            async with pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO chunks (document_id, chunk_index, raw_text, raw_text_len)
                    VALUES ($1, $2, $3, $4)
                    """,
                    [(r[0], r[1], r[2], r[3]) for r in rows],
                )
                # Update embeddings separately (executemany doesn't handle vector type well)
                for r in rows:
                    await conn.execute(
                        "UPDATE chunks SET embedding=$1 WHERE document_id=$2 AND chunk_index=$3",
                        r[4],
                        r[0],
                        r[1],
                    )

            elapsed = time.time() - started
            done = batch_start + batch_size
            log.info("seed_progress", done=done, total=count, elapsed_s=round(elapsed, 1))

        log.info("seed_complete", count=count, elapsed_s=round(time.time() - started, 1))
    finally:
        await close_pool()


async def bench() -> None:
    """Run vector search EXPLAIN ANALYZE before & after HNSW index."""
    configure_logging()
    log = get_logger("bench_vectors")
    pool = await init_pool()
    try:
        async with pool.acquire() as conn:
            # Pick a random existing chunk's embedding as the query vector
            row = await conn.fetchrow("SELECT id, embedding FROM chunks ORDER BY RANDOM() LIMIT 1")
            if row is None:
                log.error("no_chunks_to_bench")
                return
            query_vec = row["embedding"]
            log.info("bench_query_vector", sample_id=str(row["id"]))

        # --- BEFORE: drop HNSW index ---
        async with pool.acquire() as conn:
            await conn.execute("DROP INDEX IF EXISTS idx_chunks_embedding_hnsw;")
            log.info("=== BEFORE: Sequential Scan ===")
            plan = await conn.fetch(
                """
                EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
                SELECT id, raw_text, embedding <=> $1 AS distance
                FROM chunks
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> $1
                LIMIT 5
                """,
                query_vec,
            )
            for line in plan:
                print("   ", line[0])

        # --- CREATE HNSW index ---
        async with pool.acquire() as conn:
            log.info("=== Creating HNSW index (m=16, ef_construction=64) ===")
            started = time.time()
            await conn.execute("""
                CREATE INDEX idx_chunks_embedding_hnsw
                ON chunks USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
                """)
            log.info("hnsw_created", elapsed_s=round(time.time() - started, 1))

        # --- AFTER: with HNSW index ---
        async with pool.acquire() as conn:
            log.info("=== AFTER: HNSW Index Scan ===")
            plan = await conn.fetch(
                """
                EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
                SELECT id, raw_text, embedding <=> $1 AS distance
                FROM chunks
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> $1
                LIMIT 5
                """,
                query_vec,
            )
            for line in plan:
                print("   ", line[0])
    finally:
        await close_pool()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "bench"
    if cmd == "seed":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 100_000
        asyncio.run(seed(n))
    elif cmd == "bench":
        asyncio.run(bench())
    else:
        print("Usage: python seed_vectors.py [seed|bench] [count]")
        sys.exit(1)
