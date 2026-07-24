"""
/v1/chat/completions — OpenAI-compatible endpoint (Day 5, Day 6, Day 7).

Features:
  - Exact-match semantic cache (Day 5)
  - SSE streaming passthrough (Day 6)
  - CCR state machine with retrieve_original_text tool (Day 7)
  - Cost tracking via RequestLog (Day 5)
  - Auth + rate limit (Day 8)
"""

from __future__ import annotations

import time
import uuid
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import authenticate
from app.cache import cache_get, cache_set
from app.config import get_settings
from app.db import get_pool
from app.logging_config import get_logger
from app.llm.ccr import run_ccr_loop
from app.llm.openai_client import OpenAIError, create_chat_completion, stream_chat_completion
from app.metrics import (
    api_latency_seconds,
    in_flight_requests,
    llm_cost_usd_total,
    llm_requests_total,
    tokens_saved_total,
)
from app.rate_limit import check_rate_limit

router = APIRouter(tags=["chat"])
log = get_logger(__name__)


# ----- OpenAI-compatible request schemas -----


class ChatMessage(BaseModel):
    role: str
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: list[ChatMessage]
    temperature: float = 0.2
    stream: bool = False
    max_tokens: Optional[int] = None
    # Headroom extension: opt into CCR agentic retrieval
    use_ccr: bool = Field(default=False, description="Enable Reversible Compression retrieval loop")
    context_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)


# ----- Helpers -----


async def _retrieve_context(query: str, top_k: int) -> list[dict[str, Any]]:
    """
    Embed the query and run a vector search against `chunks.embedding`.
    Returns [{"chunk_id", "crushed_text", "score"}, ...]
    """
    from app.llm.openai_client import create_embedding

    try:
        q_vec = await create_embedding(query)
    except OpenAIError as exc:
        log.error("embed_query_failed", error=str(exc))
        return []

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, raw_text, embedding <=> $1 AS distance
            FROM chunks
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1
            LIMIT $2
            """,
            q_vec,
            top_k,
        )

    return [
        {
            "chunk_id": str(r["id"]),
            "crushed_text": r["raw_text"],
            "score": 1.0 - float(r["distance"]),  # cosine similarity
        }
        for r in rows
    ]


async def _log_request(
    api_key_id: Optional[str],
    user_id: Optional[str],
    endpoint: str,
    method: str,
    status_code: int,
    cache_hit: bool,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    latency_ms: int,
    request_id: str,
    error: Optional[str] = None,
) -> None:
    """Persist a row to request_logs."""
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO request_logs
                    (api_key_id, user_id, endpoint, method, status_code,
                     cache_hit, input_tokens, output_tokens, cost_usd,
                     latency_ms, request_id, error)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                uuid.UUID(api_key_id) if api_key_id else None,
                uuid.UUID(user_id) if user_id else None,
                endpoint,
                method,
                status_code,
                cache_hit,
                input_tokens,
                output_tokens,
                cost_usd,
                latency_ms,
                request_id,
                error,
            )
    except Exception as exc:
        log.error("request_log_failed", error=str(exc))


def _approx_tokens(text: str) -> int:
    """Rough token count: 1 token ≈ 4 chars."""
    return max(1, len(text) // 4)


def _cost(input_tokens: int, output_tokens: int) -> float:
    s = get_settings()
    return round(
        (input_tokens / 1000.0) * s.cost_input_per_1k
        + (output_tokens / 1000.0) * s.cost_output_per_1k,
        6,
    )


# ----- Endpoint -----


@router.post("/v1/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    response: Response,
    auth_ctx: dict = Depends(authenticate),
) -> Any:
    """OpenAI-compatible chat completions endpoint."""
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = time.time()
    in_flight_requests.inc()

    settings = get_settings()

    try:
        # --- Rate limit ---
        await check_rate_limit(auth_ctx["api_key_id"], "chat", settings.rate_limit_rpm)

        # --- Extract last user message as the query ---
        user_msgs = [m for m in body.messages if m.role == "user"]
        if not user_msgs:
            raise HTTPException(status_code=400, detail="No user message")
        query = user_msgs[-1].content

        # --- Cache check ---
        cache_payload = await cache_get(query, "chat", body.context_id)
        if cache_payload is not None:
            elapsed_ms = int((time.time() - started) * 1000)
            tokens_saved_total.labels(endpoint="chat").inc(
                cache_payload.get("input_tokens", 0) + cache_payload.get("output_tokens", 0)
            )
            await _log_request(
                api_key_id=auth_ctx["api_key_id"],
                user_id=auth_ctx["user_id"],
                endpoint="/v1/chat/completions",
                method="POST",
                status_code=200,
                cache_hit=True,
                input_tokens=cache_payload.get("input_tokens", 0),
                output_tokens=cache_payload.get("output_tokens", 0),
                cost_usd=0.0,
                latency_ms=elapsed_ms,
                request_id=request_id,
            )
            api_latency_seconds.labels(endpoint="chat", method="POST").observe(elapsed_ms / 1000.0)
            response.headers["X-Cache"] = "HIT"
            return cache_payload["response"]

        # --- Build message list ---
        messages = [{"role": m.role, "content": m.content} for m in body.messages]

        # --- CCR agentic loop OR direct call ---
        if body.use_ccr:
            chunks = await _retrieve_context(query, body.top_k)
            log.info("ccr_context_retrieved", chunks=len(chunks), query=query[:80])

            if body.stream:
                # Stream the FINAL post-tool-call answer
                async def _stream_ccr() -> AsyncIterator[str]:
                    try:
                        result = await run_ccr_loop(
                            system_prompt=(
                                "You are a helpful assistant. Use "
                                "retrieve_original_text when you need exact detail."
                            ),
                            user_query=query,
                            context_chunks=chunks,
                            stream=True,
                        )
                        # result is an async iterator of SSE lines
                        async for chunk in result:
                            yield chunk
                    finally:
                        elapsed_ms = int((time.time() - started) * 1000)
                        in_flight_requests.dec()
                        api_latency_seconds.labels(endpoint="chat", method="POST").observe(
                            elapsed_ms / 1000.0
                        )
                        await _log_request(
                            api_key_id=auth_ctx["api_key_id"],
                            user_id=auth_ctx["user_id"],
                            endpoint="/v1/chat/completions",
                            method="POST",
                            status_code=200,
                            cache_hit=False,
                            input_tokens=0,
                            output_tokens=0,
                            cost_usd=0.0,
                            latency_ms=elapsed_ms,
                            request_id=request_id,
                        )

                return StreamingResponse(
                    _stream_ccr(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                        "X-Request-Id": request_id,
                    },
                )

            # Non-stream CCR
            result = await run_ccr_loop(
                system_prompt=(
                    "You are a helpful assistant. Use retrieve_original_text "
                    "when you need exact detail."
                ),
                user_query=query,
                context_chunks=chunks,
                stream=False,
            )
            content = result["content"]
            input_tokens = _approx_tokens(query)
            output_tokens = _approx_tokens(content)
            cost = _cost(input_tokens, output_tokens)
            llm_cost_usd_total.labels(model=settings.openai_chat_model).inc(cost)
            llm_requests_total.labels(model=settings.openai_chat_model, endpoint="chat").inc()

            payload = {
                "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": body.model or settings.openai_chat_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": input_tokens,
                    "completion_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
                "ccr_meta": {
                    "iterations": result.get("iterations"),
                    "tool_calls_made": result.get("tool_calls_made"),
                    "context_chunks": len(chunks),
                },
            }

            await cache_set(query, "chat", payload, body.context_id)

            elapsed_ms = int((time.time() - started) * 1000)
            await _log_request(
                api_key_id=auth_ctx["api_key_id"],
                user_id=auth_ctx["user_id"],
                endpoint="/v1/chat/completions",
                method="POST",
                status_code=200,
                cache_hit=False,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                latency_ms=elapsed_ms,
                request_id=request_id,
            )
            api_latency_seconds.labels(endpoint="chat", method="POST").observe(elapsed_ms / 1000.0)
            response.headers["X-Cache"] = "MISS"
            response.headers["X-Request-Id"] = request_id
            return payload

        # --- Direct (non-CCR) path ---
        if body.stream:

            async def _stream_passthrough() -> AsyncIterator[str]:
                total_output = 0
                try:
                    async for chunk in stream_chat_completion(
                        messages=messages, temperature=body.temperature
                    ):
                        total_output += len(chunk)
                        yield chunk
                finally:
                    elapsed_ms = int((time.time() - started) * 1000)
                    in_flight_requests.dec()
                    api_latency_seconds.labels(endpoint="chat", method="POST").observe(
                        elapsed_ms / 1000.0
                    )
                    await _log_request(
                        api_key_id=auth_ctx["api_key_id"],
                        user_id=auth_ctx["user_id"],
                        endpoint="/v1/chat/completions",
                        method="POST",
                        status_code=200,
                        cache_hit=False,
                        input_tokens=_approx_tokens(query),
                        output_tokens=total_output // 4,
                        cost_usd=_cost(_approx_tokens(query), total_output // 4),
                        latency_ms=elapsed_ms,
                        request_id=request_id,
                    )

            return StreamingResponse(
                _stream_passthrough(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "X-Request-Id": request_id,
                },
            )

        # Non-stream direct
        try:
            resp = await create_chat_completion(messages=messages, temperature=body.temperature)
        except OpenAIError as exc:
            raise HTTPException(status_code=502, detail=f"Upstream LLM error: {exc}")

        llm_requests_total.labels(model=settings.openai_chat_model, endpoint="chat").inc()
        input_tokens = resp.get("usage", {}).get("prompt_tokens", _approx_tokens(query))
        output_tokens = resp.get("usage", {}).get("completion_tokens", 0)
        cost = _cost(input_tokens, output_tokens)
        llm_cost_usd_total.labels(model=settings.openai_chat_model).inc(cost)

        await cache_set(query, "chat", resp, body.context_id)

        elapsed_ms = int((time.time() - started) * 1000)
        await _log_request(
            api_key_id=auth_ctx["api_key_id"],
            user_id=auth_ctx["user_id"],
            endpoint="/v1/chat/completions",
            method="POST",
            status_code=200,
            cache_hit=False,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=elapsed_ms,
            request_id=request_id,
        )
        api_latency_seconds.labels(endpoint="chat", method="POST").observe(elapsed_ms / 1000.0)
        response.headers["X-Cache"] = "MISS"
        response.headers["X-Request-Id"] = request_id
        return resp

    except HTTPException:
        raise
    except Exception as exc:
        log.exception("chat_failed", error=str(exc))
        elapsed_ms = int((time.time() - started) * 1000)
        await _log_request(
            api_key_id=auth_ctx.get("api_key_id"),
            user_id=auth_ctx.get("user_id"),
            endpoint="/v1/chat/completions",
            method="POST",
            status_code=500,
            cache_hit=False,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=elapsed_ms,
            request_id=request_id,
            error=str(exc)[:500],
        )
        raise HTTPException(status_code=500, detail="Internal error")
    finally:
        in_flight_requests.dec()
