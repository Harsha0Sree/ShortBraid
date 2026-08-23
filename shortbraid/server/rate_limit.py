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

from shortbraid.server.config import get_settings
from shortbraid.server.logging_config import get_logger
from shortbraid.server.metrics import rate_limit_rejections_total
from shortbraid.server.redis_client import get_redis

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
    pipe.zrange(key, 0, 0, withscores=True)  # 3. get oldest element in window
    pipe.zadd(key, {str(now): now})  # 4. add (optimistically)
    pipe.expire(key, window_seconds + 5)  # 5. TTL cleanup
    results = await pipe.execute()

    count = results[1]
    oldest_elements = results[2]
    if count >= limit:
        # Rollback the optimistic add
        await redis.zrem(key, str(now))
        rate_limit_rejections_total.labels(endpoint=endpoint).inc()
        if oldest_elements:
            oldest_ts = float(oldest_elements[0][1])
            retry_after = max(1, int(oldest_ts + window_seconds - now))
        else:
            retry_after = window_seconds
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
            headers={"Retry-After": str(retry_after)},
        )
