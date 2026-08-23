"""
Redis client (Day 3, Day 5, Day 8).

Used for:
  - arq task queue (Day 3) — Redis List acting as FIFO
  - Semantic exact-match cache (Day 5)
  - Sliding-window rate limiter via ZSET (Day 8)
"""

from __future__ import annotations

from typing import Optional

import redis.asyncio as aioredis

from shortbraid.server.config import get_settings
from shortbraid.server.logging_config import get_logger

log = get_logger(__name__)

_redis: Optional[aioredis.Redis] = None


async def init_redis() -> aioredis.Redis:
    global _redis
    if _redis is not None:
        return _redis

    settings = get_settings()
    _redis = aioredis.from_url(
        settings.redis_url,
        max_connections=50,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
        retry_on_timeout=True,
    )
    # Verify connectivity
    try:
        await _redis.ping()
        safe_url = settings.redis_url
        if settings.redis_password:
            safe_url = safe_url.replace(settings.redis_password, "***")
        log.info("redis_connected", url=safe_url)
    except Exception as exc:
        log.error("redis_connect_failed", error=str(exc))
        raise
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        log.info("redis_closed")


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialized. Call init_redis() at startup.")
    return _redis
