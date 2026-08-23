"""
/health endpoint (Day 1).

Pings DB and Redis with raw queries — no ORM, no caching. Returns 503 if any
backing service is down so Kubernetes/Docker can restart the container.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from shortbraid.server import db as _db
from shortbraid.server import redis_client as _redis_mod
from shortbraid.server.logging_config import get_logger

router = APIRouter(tags=["health"])
log = get_logger(__name__)


@router.get("/health")
async def health(response: Response) -> dict:
    """
    Liveness + readiness combined.
    Returns {"db": "ok", "redis": "ok", "minio": "ok"} and 200 if all green.
    Returns 503 with the failing component marked "down" otherwise.
    """
    db_status = "ok"
    redis_status = "ok"
    minio_status = "ok"
    http_status = status.HTTP_200_OK

    # --- DB ping ---
    if _db._pool is None:
        db_status = "down"
    else:
        try:
            async with _db._pool.acquire() as conn:
                val = await conn.fetchval("SELECT 1")
                if val != 1:
                    db_status = "degraded"
        except Exception as exc:
            log.error("health_db_fail", error=str(exc))
            db_status = "down"

    # --- Redis ping ---
    if _redis_mod._redis is None:
        redis_status = "down"
    else:
        try:
            pong = await _redis_mod._redis.ping()
            if not pong:
                redis_status = "degraded"
        except Exception as exc:
            log.error("health_redis_fail", error=str(exc))
            redis_status = "down"

    # --- MinIO ping ---
    try:
        from shortbraid.server.minio_client import check_s3_health

        if not check_s3_health():
            minio_status = "down"
    except Exception as exc:
        log.error("health_minio_fail", error=str(exc))
        minio_status = "down"

    if db_status != "ok" or redis_status != "ok" or minio_status != "ok":
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE

    response.status_code = http_status
    return {"db": db_status, "redis": redis_status, "minio": minio_status}
