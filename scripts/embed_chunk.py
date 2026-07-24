"""
Day 4 deliverable — embed a single chunk via OpenAI and persist to Postgres.

Run:
    python scripts/embed_chunk.py <chunk_id>

If chunk_id is omitted, picks the oldest chunk without an embedding.
Pass OPENAI_API_KEY=bad-key to watch tenacity retry 3x then fail.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from typing import Optional

# Allow running as a script (not a package) — must come before app.* imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.db import init_pool, close_pool  # noqa: E402
from app.logging_config import configure_logging, get_logger  # noqa: E402
from app.llm.openai_client import OpenAIError, create_embedding  # noqa: E402
from app.metrics import llm_cost_usd_total  # noqa: E402


async def embed_one(chunk_id: Optional[str] = None) -> dict:
    configure_logging()
    log = get_logger("embed_chunk")
    settings = get_settings()

    pool = await init_pool()
    try:
        async with pool.acquire() as conn:
            if chunk_id:
                row = await conn.fetchrow(
                    "SELECT id, raw_text FROM chunks WHERE id=$1",
                    uuid.UUID(chunk_id),
                )
            else:
                row = await conn.fetchrow("""
                    SELECT id, raw_text FROM chunks
                    WHERE embedding IS NULL
                    ORDER BY created_at ASC LIMIT 1
                    """)

        if row is None:
            log.warning("no_chunk_to_embed")
            return {"ok": False, "error": "no chunk found"}

        log.info("embedding_chunk", chunk_id=str(row["id"]), text_len=len(row["raw_text"]))

        embedding = await create_embedding(row["raw_text"])
        log.info("embedding_received", dims=len(embedding))

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE chunks
                SET embedding=$1, model=$2, tokens=$3
                WHERE id=$4
                """,
                embedding,
                settings.openai_embed_model,
                len(row["raw_text"]) // 4,
                row["id"],
            )

        cost = (len(row["raw_text"]) // 4 / 1000.0) * settings.cost_input_per_1k
        llm_cost_usd_total.labels(model=settings.openai_embed_model).inc(cost)
        log.info("embedded", chunk_id=str(row["id"]), cost_usd=cost)
        return {
            "ok": True,
            "chunk_id": str(row["id"]),
            "tokens": len(row["raw_text"]) // 4,
            "cost_usd": cost,
        }

    finally:
        await close_pool()


if __name__ == "__main__":
    chunk_id = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        result = asyncio.run(embed_one(chunk_id))
        print(result)
    except OpenAIError as exc:
        print(f"[FAIL] OpenAI error after retries: {exc}")
        sys.exit(1)
