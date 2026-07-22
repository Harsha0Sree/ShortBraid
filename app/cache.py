"""
Exact-match semantic cache (Day 5).

For now we implement EXACT-match caching (SHA256 of (query, context_id)).
Approximate / embedding-based semantic cache is a future enhancement.

Cache hit  → return payload immediately, log cost_saved
Cache miss → proceed to LLM, store response with TTL
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from app.config import get_settings
from app.logging_config import get_logger
from app.metrics import cache_hits_total, cache_misses_total
from app.redis_client import get_redis

log = get_logger(__name__)


def _cache_key(query: str, endpoint: str, context_id: Optional[str] = None) -> str:
    """SHA256 of (endpoint, context_id, query) — collision-resistant."""
    h = hashlib.sha256()
    h.update(endpoint.encode())
    h.update(b"\x00")
    h.update((context_id or "global").encode())
    h.update(b"\x00")
    h.update(query.strip().lower().encode())
    return f"cache:{endpoint}:{h.hexdigest()}"


async def cache_get(
    query: str, endpoint: str, context_id: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """Returns cached payload if present, else None."""
    redis = get_redis()
    key = _cache_key(query, endpoint, context_id)
    raw = await redis.get(key)
    if raw is None:
        cache_misses_total.labels(endpoint=endpoint).inc()
        log.info("cache_miss", key=key[:32] + "...", endpoint=endpoint)
        return None
    cache_hits_total.labels(endpoint=endpoint).inc()
    log.info("cache_hit", key=key[:32] + "...", endpoint=endpoint)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("cache_corrupt", key=key)
        await redis.delete(key)
        return None


async def cache_set(
    query: str,
    endpoint: str,
    payload: dict[str, Any],
    context_id: Optional[str] = None,
    ttl: Optional[int] = None,
) -> None:
    settings = get_settings()
    redis = get_redis()
    key = _cache_key(query, endpoint, context_id)
    await redis.set(
        key,
        json.dumps(payload, ensure_ascii=False),
        ex=ttl or settings.cache_ttl_seconds,
    )
    log.info("cache_set", key=key[:32] + "...", ttl=ttl or settings.cache_ttl_seconds)
