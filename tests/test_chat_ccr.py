"""Tests for Chat Completions and CCR Agentic Loop (seam:chat_api, seam:ccr)."""

import json
import uuid
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from shortbraid.server.llm.ccr import _fetch_original_text, run_ccr_loop
from shortbraid.server.main import app
from tests.conftest import MockPool, MockRedisPipeline


@pytest.mark.asyncio
async def test_fetch_original_text_with_minio_fallback():
    chunk_id = str(uuid.uuid4())
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "original_text": None,  # Not directly on non-zero chunk
        "raw_text": "crushed text",
        "minio_object": "s3://shortbraid-ingest/documents/test.json",
    }
    mock_pool = MockPool(mock_conn)

    with (
        patch("shortbraid.server.llm.ccr.get_pool", return_value=mock_pool),
        patch("shortbraid.server.minio_client.get_object", return_value=b'{"full":"uncompressed original log"}'),
    ):
        text = await _fetch_original_text(chunk_id)
        assert text == '{"full":"uncompressed original log"}'


@pytest.mark.asyncio
async def test_ccr_loop_dispatches_tool_call_and_terminates():
    chunk_id = str(uuid.uuid4())
    context_chunks = [{"chunk_id": chunk_id, "crushed_text": "crushed", "score": 0.95}]

    # Step 1: Model asks for retrieve_original_text tool call
    step1_response = {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "retrieve_original_text",
                                "arguments": json.dumps({"chunk_id": chunk_id}),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }

    # Step 2: Model returns final answer after receiving tool output
    step2_response = {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "The uncompressed timestamp was 2024-01-01T12:00:00Z.",
                    "tool_calls": None,
                },
                "finish_reason": "stop",
            }
        ]
    }

    mock_llm = AsyncMock(side_effect=[step1_response, step2_response])

    with (
        patch("shortbraid.server.llm.ccr.create_chat_completion", mock_llm),
        patch(
            "shortbraid.server.llm.ccr.execute_tool",
            AsyncMock(return_value="2024-01-01T12:00:00Z full uncompressed"),
        ),
    ):
        result = await run_ccr_loop(
            system_prompt="You are an assistant",
            user_query="What was the timestamp?",
            context_chunks=context_chunks,
            stream=False,
        )

        assert result["content"] == "The uncompressed timestamp was 2024-01-01T12:00:00Z."
        assert result["tool_calls_made"] == 1
        assert result["iterations"] == 2


def test_chat_completions_endpoint_standard(app):
    with TestClient(app) as client:
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "id": uuid.uuid4(),
            "user_id": uuid.uuid4(),
            "name": "test_key",
            "is_active": True,
        }
        mock_pool = MockPool(mock_conn)
        mock_redis = AsyncMock()
        mock_redis.pipeline = lambda: MockRedisPipeline()
        mock_redis.get.return_value = None  # Cache miss

        openai_resp = {
            "id": "chatcmpl-test",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello there!"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }

        with (
            patch("shortbraid.server.auth.get_pool", return_value=mock_pool),
            patch("shortbraid.server.rate_limit.get_redis", return_value=mock_redis),
            patch("shortbraid.server.cache.get_redis", return_value=mock_redis),
            patch("shortbraid.server.routers.chat.get_pool", return_value=mock_pool),
            patch("shortbraid.server.routers.chat.create_chat_completion", AsyncMock(return_value=openai_resp)),
        ):

            resp = client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer sk_test_key_123"},
                json={
                    "messages": [{"role": "user", "content": "Hi"}],
                    "stream": False,
                    "use_ccr": False,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["choices"][0]["message"]["content"] == "Hello there!"
            assert resp.headers.get("X-Cache") == "MISS"
