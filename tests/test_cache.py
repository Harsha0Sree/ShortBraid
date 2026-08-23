"""Unit tests for exact-match semantic cache (seam:cache)."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from shortbraid.server.cache import _cache_key, cache_get, cache_set


def test_cache_key_generation():
    k1 = _cache_key("What is the error?", "chat", "tenant_a")
    k2 = _cache_key("what is the error? ", "chat", "tenant_a")
    k3 = _cache_key("What is the error?", "chat", "tenant_b")
    k4 = _cache_key("What is the error?", "ingest", "tenant_a")

    assert k1 == k2  # Case & whitespace normalization
    assert k1 != k3  # Distinct contexts
    assert k1 != k4  # Distinct endpoints
    assert k1.startswith("cache:chat:")


@pytest.mark.asyncio
async def test_cache_get_miss():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with patch("shortbraid.server.cache.get_redis", return_value=mock_redis):
        result = await cache_get("unknown query", "chat", "tenant_1")
        assert result is None
        mock_redis.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_get_hit():
    mock_redis = AsyncMock()
    stored_data = {
        "response": {"choices": [{"message": {"content": "cached reply"}}]},
        "input_tokens": 10,
    }
    mock_redis.get.return_value = json.dumps(stored_data)

    with patch("shortbraid.server.cache.get_redis", return_value=mock_redis):
        result = await cache_get("known query", "chat", "tenant_1")
        assert result == stored_data
        mock_redis.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_get_corrupted_json():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "{invalid-json"

    with patch("shortbraid.server.cache.get_redis", return_value=mock_redis):
        result = await cache_get("corrupt query", "chat", "tenant_1")
        assert result is None
        mock_redis.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_set_payload():
    mock_redis = AsyncMock()
    payload = {"data": "test"}

    with patch("shortbraid.server.cache.get_redis", return_value=mock_redis):
        await cache_set("my query", "chat", payload, context_id="ctx1", ttl=600)
        mock_redis.set.assert_awaited_once()
        args, kwargs = mock_redis.set.call_args
        assert args[0].startswith("cache:chat:")
        assert json.loads(args[1]) == payload
        assert kwargs.get("ex") == 600
