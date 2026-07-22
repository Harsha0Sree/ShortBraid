"""
Sliding-window rate limiter (Day 8).

Implementation: a Redis ZSET of request timestamps per (api_key_id, endpoint).
On each request:
  1. ZREMRANGEBYSCORE to evict timestamps older than (now - window)
  2. ZCARD to count current requests in the window
  3. If count >= limit, reject with 429
  4. Else ZADD the new timestamp and set TTL on the key

The ZSET is the canonical sliding-window algorithm — not a fixed counter,
which would allow 2x burst at the boundary.
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import HTTPException, status

from app.config import get_settings
from app.logging_config import get_logger
from app.metrics import rate_limit_rejections_total
from app.redis_client import get_redis

log = get_logger(__name__)


async def check_rate_limit(
    identifier: str,
    endpoint: str,
    limit_per_min: Optional[int] = None,
) -> None:
    """Raise 429 if the (identifier, endpoint) bucket is saturated."""
    settings = get_settings()
    limit = limit_per_min or settings.rate_limit_rpm
    window_seconds = 60

    redis = get_redis()
    now = time.time()
    cutoff = now - window_seconds
    key = f"rl:{endpoint}:{identifier}"

    # Atomic via pipeline (still multi-step, but no race within MULTI/EXEC)
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, cutoff)  # 1. evict old
    pipe.zcard(key)  # 2. count current
    pipe.zadd(key, {str(now): now})  # 3. add (optimistically)
    pipe.expire(key, window_seconds + 5)  # 4. TTL cleanup
    results = await pipe.execute()

    count = results[1]
    if count >= limit:
        # Rollback the optimistic add
        await redis.zrem(key, str(now))
        rate_limit_rejections_total.labels(endpoint=endpoint).inc()
        retry_after = int(window_seconds - (now - cutoff))
        log.warning(
            "rate_limited",
            identifier=identifier,
            endpoint=endpoint,
            count=count,
            limit=limit,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {limit} req/min",
            headers={"Retry-After": str(max(retry_after, 1))},
        )
