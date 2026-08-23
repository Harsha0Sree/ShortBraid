"""FastAPI dependency injection."""

from __future__ import annotations

from shortbraid.server.auth import authenticate, optional_auth
from shortbraid.server.db import get_pool
from shortbraid.server.redis_client import get_redis

__all__ = ["authenticate", "optional_auth", "get_pool", "get_redis"]
