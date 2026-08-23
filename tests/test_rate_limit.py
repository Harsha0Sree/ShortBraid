"""Unit tests for sliding-window rate limiter (seam:rate_limit)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from shortbraid.server.rate_limit import check_rate_limit


@pytest.mark.asyncio
async def test_rate_limit_allows_under_limit():
    mock_redis = AsyncMock()
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[0, 2, [("100.0", 100.0)], 1, True])
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    with patch("shortbraid.server.rate_limit.get_redis", return_value=mock_redis):
        # Should not raise
        await check_rate_limit("test_user", "test_endpoint", limit_per_min=5)


@pytest.mark.asyncio
async def test_rate_limit_rejects_and_computes_accurate_retry_after():
    mock_redis = AsyncMock()
    mock_pipe = MagicMock()
    now = 1000.0
    oldest_ts = 960.0  # 40 seconds ago in a 60-second window -> 20s remaining

    # count is 5 (limit is 5) -> rejection
    mock_pipe.execute = AsyncMock(return_value=[0, 5, [("960.0", oldest_ts)], 1, True])
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    with (
        patch("shortbraid.server.rate_limit.get_redis", return_value=mock_redis),
        patch("time.time", return_value=now),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await check_rate_limit("test_user", "test_endpoint", limit_per_min=5)

        assert exc_info.value.status_code == 429
        assert "Rate limit exceeded" in exc_info.value.detail
        # Window is 60s, oldest was at 960.0, current is 1000.0 -> retry after should be ~20-21
        retry_after = int(exc_info.value.headers["Retry-After"])
        assert 20 <= retry_after <= 21
        # Check optimistic add was rolled back
        mock_redis.zrem.assert_awaited_once()
