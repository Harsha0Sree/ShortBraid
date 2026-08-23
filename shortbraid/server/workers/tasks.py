"""
arq background worker tasks (Day 3, Day 4).

The /ingest API enqueues a `crush_document` job. The worker:
  1. Marks document status='processing'
  2. Downloads raw text from MinIO
  3. Runs SmartCrusher
  4. Splits into chunks
  5. Embeds each chunk via OpenAI (Day 4, retryable)
  6. Inserts chunk rows with vector
  7. Marks document status='embedded'

On failure: marks 'failed' and stores the error.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from shortbraid.server.config import get_settings
from shortbraid.server.db import get_pool, init_pool
from shortbraid.server.logging_config import configure_logging, get_logger
from shortbraid.server.llm.openai_client import OpenAIError, create_embedding
from shortbraid.server.metrics import llm_cost_usd_total, queue_depth
from shortbraid.server.minio_client import get_object, init_s3
from shortbraid.server.redis_client import get_redis, init_redis
from shortbraid.server.workers.crusher import chunk_text, crush
from arq.cron import cron

log = get_logger(__name__)


async def crush_document(ctx: dict[str, Any], document_id: str) -> dict[str, Any]:
    """
    Crush + chunk + embed a document. arq entrypoint.

    Args:
        ctx: arq worker context
        document_id: UUID string of the documents row
    """
    configure_logging()
    doc_uuid = uuid.UUID(document_id)
    started = time.time()

    pool = get_pool()

    # 1. Mark processing
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE documents SET status='processing', updated_at=now() WHERE id=$1",
            doc_uuid,
        )
        doc = await conn.fetchrow(
            "SELECT id, minio_object, metadata FROM documents WHERE id=$1",
            doc_uuid,
        )
    if doc is None:
        log.error("doc_not_found", document_id=document_id)
        return {"ok": False, "error": "not_found"}

    s3_uri = doc["minio_object"]
    # s3://bucket/key → key
    bucket, _, key = s3_uri.replace("s3://", "").partition("/")
    log.info("crush_start", document_id=document_id, key=key)

    try:
        # 2. Download raw
        raw_bytes = get_object(key)
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        log.info("raw_fetched", document_id=document_id, raw_len=len(raw_text))

        # 3. Crush
        result = crush(raw_text)
        log.info(
            "crushed",
            document_id=document_id,
            original_len=result.original_len,
            crushed_len=result.crushed_len,
            ratio=result.compression_ratio,
        )

        # 4. Chunk
        chunks = chunk_text(result.crushed, max_chars=4000, overlap=200)
        log.info("chunked", document_id=document_id, chunks=len(chunks))

        # 5. Embed + insert each chunk
        inserted = 0
        total_tokens = 0
        for idx, chunk_text_str in enumerate(chunks):
            try:
                embedding = await create_embedding(chunk_text_str)
            except OpenAIError as exc:
                log.error("embed_failed", document_id=document_id, chunk=idx, error=str(exc))
                # Continue — partial embedding is still useful. Mark failed chunks as null.
                embedding = None
            else:
                # Approximate tokens as len/4 (OpenAI's rough rule)
                total_tokens += len(chunk_text_str) // 4

            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO chunks
                        (document_id, chunk_index, raw_text, raw_text_len,
                         original_text, original_len, embedding, model, tokens)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    doc_uuid,
                    idx,
                    chunk_text_str,
                    len(chunk_text_str),
                    # Store the original segment if we kept it; here we store the raw text
                    # pre-crush form would require per-chunk reverse mapping. We store the
                    # full raw_text on the first chunk for CCR retrieval fallback.
                    raw_text if idx == 0 else None,
                    len(raw_text) if idx == 0 else 0,
                    embedding,
                    get_settings().openai_embed_model,
                    len(chunk_text_str) // 4,
                )
            inserted += 1

        # 6. Mark embedded
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE documents
                SET status='embedded',
                    raw_sha256=$1,
                    crushed_sha256=$2,
                    updated_at=now()
                WHERE id=$3
                """,
                result.original_sha256,
                result.crushed_sha256,
                doc_uuid,
            )

        # Cost tracking — rough estimate
        settings = get_settings()
        embed_cost = (total_tokens / 1000.0) * settings.cost_input_per_1k
        llm_cost_usd_total.labels(model=settings.openai_embed_model).inc(embed_cost)

        elapsed_ms = int((time.time() - started) * 1000)
        log.info(
            "crush_complete",
            document_id=document_id,
            chunks_inserted=inserted,
            tokens=total_tokens,
            cost_usd=round(embed_cost, 6),
            elapsed_ms=elapsed_ms,
        )
        return {
            "ok": True,
            "document_id": document_id,
            "chunks_inserted": inserted,
            "tokens": total_tokens,
            "compression_ratio": result.compression_ratio,
            "elapsed_ms": elapsed_ms,
        }

    except Exception as exc:
        log.exception("crush_failed", document_id=document_id, error=str(exc))
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE documents SET status='failed', error=$1, updated_at=now() WHERE id=$2",
                str(exc)[:1000],
                doc_uuid,
            )
        return {"ok": False, "error": str(exc)}


async def on_startup(ctx: dict[str, Any]) -> None:
    """arq worker startup hook."""
    configure_logging()
    await init_pool()
    await init_redis()
    init_s3()
    log.info("worker_started", concurrency=get_settings().worker_concurrency)


async def on_shutdown(ctx: dict[str, Any]) -> None:
    from shortbraid.server.db import close_pool
    from shortbraid.server.redis_client import close_redis

    await close_redis()
    await close_pool()
    log.info("worker_stopped")


async def tick_queue_depth(ctx: dict[str, Any]) -> None:
    """Periodic task: report arq queue depth to Prometheus."""
    redis = get_redis()
    depth = await redis.llen("arq:queue")
    queue_depth.set(depth)


class WorkerSettings:
    """arq worker config — referenced by `arq shortbraid.server.workers.tasks.WorkerSettings`."""

    functions = [crush_document]
    on_startup = on_startup
    on_shutdown = on_shutdown
    cron_jobs = [
        # Every 30s, sample the queue depth for Prometheus
        cron(tick_queue_depth, hour=None, minute=None, second={0, 30}),
    ]
    max_jobs = 50
    job_timeout = 600
    max_tries = 3
