"""
POST /api/v1/ingest/  (Day 2, Day 3)

Receives a JSON payload, saves raw bytes to MinIO, inserts a documents row,
enqueues a crush_document job to arq, returns 202 Accepted immediately.

The web server does NO heavy CPU work — that's the producer/consumer split.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from shortbraid.server.auth import authenticate
from shortbraid.server.config import get_settings
from shortbraid.server.db import get_pool
from shortbraid.server.logging_config import get_logger
from shortbraid.server.minio_client import put_object
from shortbraid.server.rate_limit import check_rate_limit

router = APIRouter(prefix="/api/v1", tags=["ingest"])
log = get_logger(__name__)


class IngestRequest(BaseModel):
    """JSON body for /ingest."""

    content: str = Field(..., description="Raw text content (JSON, logs, etc.)")
    source: str = Field(default="api", description="Origin label")
    content_type: str = Field(default="application/json")
    context_id: Optional[str] = Field(default=None, description="Logical grouping")
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    document_id: str
    status: str
    minio_object: str
    size_bytes: int
    accepted_at: str


async def _process_ingest(
    raw_bytes: bytes,
    source: str,
    content_type: str,
    metadata: dict[str, Any],
    auth_ctx: dict,
) -> IngestResponse:
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Empty content")

    settings = get_settings()
    doc_id = uuid.uuid4()
    object_key = f"documents/{doc_id}.json"

    # --- Upload to MinIO ---
    try:
        s3_uri = put_object(object_key, raw_bytes, content_type=content_type)
    except Exception as exc:
        log.exception("minio_put_failed", document_id=str(doc_id), error=str(exc))
        raise HTTPException(status_code=502, detail=f"Object storage failure: {exc}")

    # --- Insert documents row ---
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO documents
                (id, source, content_type, size_bytes, status,
                 minio_object, metadata, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'pending', $5, $6, now(), now())
            """,
            doc_id,
            source,
            content_type,
            len(raw_bytes),
            s3_uri,
            metadata,
        )

    # --- Enqueue crush job ---
    try:
        redis_settings = RedisSettings(host=settings.redis_host, port=settings.redis_port)
        arq_pool = await create_pool(redis_settings)
        job = await arq_pool.enqueue_job(
            "crush_document",
            document_id=str(doc_id),
            _queue_name="arq:queue",
        )
        log.info(
            "ingest_enqueued",
            document_id=str(doc_id),
            job_id=job.job_id if job else None,
            size_bytes=len(raw_bytes),
            user_id=auth_ctx["user_id"],
        )
    except Exception as exc:
        log.exception("enqueue_failed", document_id=str(doc_id), error=str(exc))
        # Roll back the document row so we don't have an orphan
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE documents SET status='failed', error=$1 WHERE id=$2",
                f"enqueue_failed: {exc}",
                doc_id,
            )
        raise HTTPException(status_code=503, detail="Queue unavailable")

    return IngestResponse(
        document_id=str(doc_id),
        status="pending",
        minio_object=s3_uri,
        size_bytes=len(raw_bytes),
        accepted_at=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
@router.post("/ingest/", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest(
    request: Request,
    auth_ctx: dict = Depends(authenticate),
    file: Optional[UploadFile] = File(default=None),
    source: Optional[str] = Form(default=None),
) -> IngestResponse:
    """Accept a document for ingestion via JSON or multipart upload. Returns 202."""
    settings = get_settings()

    # --- Rate limit (per API key) ---
    await check_rate_limit(auth_ctx["api_key_id"], "ingest", settings.rate_limit_rpm)

    content_type_header = request.headers.get("content-type", "")

    # Multipart file upload
    if "multipart/form-data" in content_type_header or file is not None:
        if file is None:
            raise HTTPException(status_code=400, detail="Missing file in multipart upload")
        raw_bytes = await file.read()
        src = source or file.filename or "file_upload"
        ctype = file.content_type or "application/octet-stream"
        meta = {"filename": file.filename}
        return await _process_ingest(raw_bytes, src, ctype, meta, auth_ctx)

    # JSON body upload
    try:
        body_json = await request.json()
        body = IngestRequest(**body_json)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}")

    return await _process_ingest(
        body.content.encode("utf-8"),
        body.source,
        body.content_type,
        body.metadata,
        auth_ctx,
    )


async def _fetch_doc_status(document_id: str) -> dict:
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid document_id UUID format")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, source, status, size_bytes, minio_object,
                   raw_sha256, crushed_sha256, error, created_at, updated_at
            FROM documents WHERE id=$1
            """,
            doc_uuid,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "document_id": str(row["id"]),
        "source": row["source"],
        "status": row["status"],
        "size_bytes": row["size_bytes"],
        "minio_object": row["minio_object"],
        "raw_sha256": row["raw_sha256"],
        "crushed_sha256": row["crushed_sha256"],
        "error": row["error"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


@router.get("/ingest/{document_id}")
@router.get("/documents/{document_id}")
async def get_document(document_id: str, auth_ctx: dict = Depends(authenticate)) -> dict:
    """Check ingestion status."""
    return await _fetch_doc_status(document_id)
