"""
Admin endpoints — API key management (Day 8).

In production this would be behind an admin token / IAM. For local dev we
expose POST /admin/api-keys to mint a key. The key is shown ONCE.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel

from shortbraid.server.auth import generate_api_key, authenticate
from shortbraid.server.config import get_settings
from shortbraid.server.db import get_pool
from shortbraid.server.logging_config import get_logger

router = APIRouter(prefix="/admin", tags=["admin"])
log = get_logger(__name__)


class CreateApiKeyRequest(BaseModel):
    user_id: Optional[str] = None
    name: str = "default"


class CreateApiKeyResponse(BaseModel):
    api_key: str
    key_id: str
    key_prefix: str
    name: str


@router.post("/api-keys", response_model=CreateApiKeyResponse)
async def create_api_key(
    body: CreateApiKeyRequest,
    x_admin_token: Optional[str] = Header(default=None),
) -> CreateApiKeyResponse:
    """Mint a new API key. The raw key is returned ONCE — only the hash is stored."""
    # Lightweight admin gate
    settings = get_settings()
    if settings.is_prod:
        admin_secret = settings.admin_api_key or settings.openai_api_key
        if not x_admin_token or not admin_secret or x_admin_token != admin_secret:
            raise HTTPException(status_code=403, detail="Admin token required in prod")

    raw_key, key_hash = generate_api_key()
    user_id = body.user_id or str(uuid.uuid4())
    key_id = uuid.uuid4()

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (id, user_id, key_hash, key_prefix, name)
            VALUES ($1, $2, $3, $4, $5)
            """,
            key_id,
            uuid.UUID(user_id),
            key_hash,
            raw_key[:12],
            body.name,
        )

    log.info("api_key_minted", key_id=str(key_id), name=body.name)
    return CreateApiKeyResponse(
        api_key=raw_key,
        key_id=str(key_id),
        key_prefix=raw_key[:12],
        name=body.name,
    )


@router.get("/api-keys")
async def list_api_keys(auth_ctx: dict = Depends(authenticate)) -> dict:
    """List active API keys for the calling user."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, key_prefix, name, created_at, is_active
            FROM api_keys
            WHERE user_id=$1 AND is_active=TRUE
            ORDER BY created_at DESC
            """,
            uuid.UUID(auth_ctx["user_id"]),
        )
    return {
        "keys": [
            {
                "id": str(r["id"]),
                "prefix": r["key_prefix"],
                "name": r["name"],
                "created_at": r["created_at"].isoformat(),
                "active": r["is_active"],
            }
            for r in rows
        ]
    }


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    auth_ctx: dict = Depends(authenticate),
) -> dict:
    """Revoke an active API key for the calling user."""
    try:
        k_uuid = uuid.UUID(key_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid key_id format")

    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE api_keys
            SET is_active = FALSE, revoked_at = now()
            WHERE id = $1 AND user_id = $2 AND is_active = TRUE
            """,
            k_uuid,
            uuid.UUID(auth_ctx["user_id"]),
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Key not found or already revoked")

    log.info("api_key_revoked", key_id=key_id, user_id=auth_ctx["user_id"])
    return {"ok": True, "revoked_key_id": key_id}
