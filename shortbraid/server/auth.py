"""
API key authentication (Day 8).

Keys are SHA256-hashed in Postgres. The client sends `Authorization: Bearer sk-...`.
We hash the incoming key and look it up in `api_keys` (indexed).
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Optional

import asyncpg
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shortbraid.server.db import get_pool
from shortbraid.server.logging_config import get_logger

log = get_logger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


def hash_api_key(raw: str) -> str:
    """SHA256 hex digest. Salt is not needed — keys are 256-bit random."""
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Returns (raw_key, key_hash). Caller stores only the hash."""
    raw = "sk_" + secrets.token_urlsafe(32)
    return raw, hash_api_key(raw)


async def authenticate(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """Validate the bearer token, attach api_key context to request.state."""
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw = creds.credentials
    key_hash = hash_api_key(raw)
    pool = get_pool()

    row: Optional[asyncpg.Record] = None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, user_id, name, is_active
            FROM api_keys
            WHERE key_hash = $1 AND is_active = TRUE AND revoked_at IS NULL
            """,
            key_hash,
        )

    if row is None:
        log.warning("auth_failed", key_prefix=raw[:8])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    ctx = {
        "api_key_id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "name": row["name"],
    }
    request.state.api_key_id = ctx["api_key_id"]
    request.state.user_id = ctx["user_id"]
    return ctx


# For endpoints that SHOULD be authed in prod but are open in dev
async def optional_auth(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[dict]:
    if creds is None:
        request.state.api_key_id = None
        request.state.user_id = None
        return None
    return await authenticate(request, creds)
