"""FastAPI dependency injection."""

from __future__ import annotations

from app.auth import authenticate, optional_auth
from app.db import get_pool
from app.redis_client import get_redis

__all__ = ["authenticate", "optional_auth", "get_pool", "get_redis"]
