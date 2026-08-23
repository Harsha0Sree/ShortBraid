"""
MinIO (S3-compatible object storage) client (Day 2).

Why object storage for blobs (not DB BLOBs):
  - Postgres TOAST allocates oversized buffers; large blobs bloat WAL.
  - S3/MinIO is horizontally scalable, content-addressed, cheap.
  - The DB row stores only the object key (s3://bucket/key).
"""

from __future__ import annotations

import io
from typing import Optional

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from shortbraid.server.config import get_settings
from shortbraid.server.logging_config import get_logger

log = get_logger(__name__)

_s3_client: Optional[object] = None


def init_s3() -> object:
    """Build a thread-safe boto3 S3 client. Idempotent."""
    global _s3_client
    if _s3_client is not None:
        return _s3_client

    settings = get_settings()
    _s3_client = boto3.client(
        "s3",
        endpoint_url=f"{'https' if settings.minio_secure else 'http'}://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name=settings.minio_region,
        config=BotoConfig(
            signature_version="s3v4",
            retries={"max_attempts": 2, "mode": "standard"},
            connect_timeout=2,
            read_timeout=10,
        ),
    )
    log.info("s3_initialized", endpoint=settings.minio_endpoint, bucket=settings.minio_bucket)
    return _s3_client


def get_s3() -> object:
    if _s3_client is None:
        raise RuntimeError("S3 client not initialized.")
    return _s3_client


def ensure_bucket_exists() -> None:
    """Idempotently create the bucket if missing."""
    settings = get_settings()
    client = get_s3()
    try:
        client.head_bucket(Bucket=settings.minio_bucket)
    except ClientError:
        log.info("creating_bucket", bucket=settings.minio_bucket)
        client.create_bucket(Bucket=settings.minio_bucket)


def put_object(key: str, data: bytes, content_type: str = "application/json") -> str:
    """Upload bytes, return the s3:// URI."""
    settings = get_settings()
    client = get_s3()
    client.upload_fileobj(
        io.BytesIO(data),
        settings.minio_bucket,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    return f"s3://{settings.minio_bucket}/{key}"


def get_object(key: str) -> bytes:
    """Download an object by key."""
    settings = get_settings()
    client = get_s3()
    buf = io.BytesIO()
    client.download_fileobj(settings.minio_bucket, key, buf)
    return buf.getvalue()


def check_s3_health() -> bool:
    """Check connectivity to S3/MinIO bucket."""
    try:
        settings = get_settings()
        client = get_s3()
        client.head_bucket(Bucket=settings.minio_bucket)
        return True
    except Exception as exc:
        log.warning("s3_health_check_failed", error=str(exc))
        return False
