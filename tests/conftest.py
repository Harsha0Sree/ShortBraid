import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

# Make app and shortbraid importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockAcquireContext:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockPool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return MockAcquireContext(self.conn)


class MockRedisPipeline:
    def __init__(self, execute_result=None):
        self.execute_result = execute_result or [0, 1, [], 1, True]

    def zremrangebyscore(self, *args, **kwargs):
        return self

    def zcard(self, *args, **kwargs):
        return self

    def zrange(self, *args, **kwargs):
        return self

    def zadd(self, *args, **kwargs):
        return self

    def expire(self, *args, **kwargs):
        return self

    async def execute(self):
        return self.execute_result


@pytest.fixture
def mock_db_pool():
    conn = AsyncMock()
    return MockPool(conn), conn


@pytest.fixture
def mock_redis_client():
    client = AsyncMock()
    client.pipeline = lambda: MockRedisPipeline()
    return client


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def app():
    with (
        patch("shortbraid.server.main.init_pool", AsyncMock(return_value=MockPool(AsyncMock()))),
        patch("shortbraid.server.main.init_redis", AsyncMock(return_value=AsyncMock())),
        patch("shortbraid.server.main.init_s3", lambda: None),
        patch("shortbraid.server.main.ensure_bucket_exists", lambda: None),
        patch("shortbraid.server.main.close_pool", AsyncMock()),
        patch("shortbraid.server.main.close_redis", AsyncMock()),
    ):
        from shortbraid.server.main import app as _app
        yield _app
