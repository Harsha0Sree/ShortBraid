"""
Postgres connection pool (Day 1, Day 10).

Raw asyncpg — no ORM, per Day 1 spec.
The pool is created once on FastAPI startup and reused across requests.
Day 10 fixes: pool size tuning to survive 50 concurrent users.
"""

from __future__ import annotations

import asyncpg
from typing import Optional

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def init_pool() -> asyncpg.Pool:
    """Create the global pool. Idempotent."""
    global _pool
    if _pool is not None:
        return _pool

    settings = get_settings()
    log.info(
        "init_pg_pool",
        host=settings.postgres_host,
        db=settings.postgres_db,
        min_size=settings.pg_pool_min,
        max_size=settings.pg_pool_max,
    )

    _pool = await asyncpg.create_pool(
        dsn=settings.postgres_dsn,
        min_size=settings.pg_pool_min,
        max_size=settings.pg_pool_max,
        max_queries=50_000,
        max_inactive_connection_lifetime=300,
        command_timeout=30,
        init=asyncpg_init,
    )
    return _pool


async def asyncpg_init(conn: asyncpg.Connection):
    """Per-connection init: register pgvector type + JSON codec."""
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    try:
        from pgvector.asyncpg import register_vector

        await register_vector(conn)
    except Exception as exc:  # pragma: no cover
        log.warning("pgvector_register_failed", error=str(exc))


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("pg_pool_closed")


def get_pool() -> asyncpg.Pool:
    """Returns the global pool. Raises if not initialized."""
    if _pool is None:
        raise RuntimeError("DB pool not initialized. Call init_pool() at startup.")
    return _pool
