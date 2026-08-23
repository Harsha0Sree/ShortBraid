"""
ShortBraid Transparent Reverse Proxy.

Intercepts LLM requests (OpenAI / Anthropic / LiteLLM), applies zero-code-change
context compression, preserves KV-cache prefixes, and forwards upstream.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, AsyncIterator

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from shortbraid.compressor import compress
from shortbraid.detector import SmartContentDetector

proxy_app = FastAPI(
    title="ShortBraid Transparent Proxy",
    description="Drop-in LLM compression gateway for OpenAI, Anthropic, and LiteLLM",
    version="0.2.0",
)

# In-memory proxy stats
_STATS = {
    "total_requests": 0,
    "total_original_tokens": 0,
    "total_compressed_tokens": 0,
    "total_tokens_saved": 0,
}


@proxy_app.get("/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": "shortbraid-proxy",
        "stats": _STATS,
    }


@proxy_app.get("/metrics")
async def metrics() -> Response:
    lines = [
        "# HELP shortbraid_proxy_requests_total Total requests processed by proxy",
        "# TYPE shortbraid_proxy_requests_total counter",
        f"shortbraid_proxy_requests_total {_STATS['total_requests']}",
        "# HELP shortbraid_tokens_saved_total Total tokens saved via compression",
        "# TYPE shortbraid_tokens_saved_total counter",
        f"shortbraid_tokens_saved_total {_STATS['total_tokens_saved']}",
        "# HELP shortbraid_original_tokens_total Total original input tokens",
        "# TYPE shortbraid_original_tokens_total counter",
        f"shortbraid_original_tokens_total {_STATS['total_original_tokens']}",
        "# HELP shortbraid_compressed_tokens_total Total compressed input tokens",
        "# TYPE shortbraid_compressed_tokens_total counter",
        f"shortbraid_compressed_tokens_total {_STATS['total_compressed_tokens']}",
    ]
    return Response("\n".join(lines) + "\n", media_type="text/plain")


@proxy_app.post("/v1/chat/completions")
async def proxy_openai_chat(request: Request) -> Response:
    """Proxy OpenAI chat completions with transparent compression."""
    body = await request.json()
    upstream_url = os.getenv("SHORTBRAID_UPSTREAM_URL", "https://api.openai.com/v1/chat/completions")
    api_key = request.headers.get("authorization") or os.getenv("OPENAI_API_KEY", "")

    # Compress incoming messages
    messages = body.get("messages", [])
    model = body.get("model", "gpt-4o")
    stream = body.get("stream", False)

    compressed_res = compress(messages, model=model)
    body["messages"] = compressed_res.messages

    # Update stats
    _STATS["total_requests"] += 1
    _STATS["total_original_tokens"] += compressed_res.original_tokens
    _STATS["total_compressed_tokens"] += compressed_res.compressed_tokens
    _STATS["total_tokens_saved"] += compressed_res.tokens_saved

    headers = {
        "Content-Type": "application/json",
        "Authorization": api_key if api_key.startswith("Bearer ") else f"Bearer {api_key}",
    }

    client = httpx.AsyncClient(timeout=120.0)

    if stream:
        async def stream_generator() -> AsyncIterator[bytes]:
            try:
                async with client.stream("POST", upstream_url, json=body, headers=headers) as upstream_resp:
                    async for chunk in upstream_resp.aiter_bytes():
                        yield chunk
            finally:
                await client.aclose()

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    try:
        upstream_resp = await client.post(upstream_url, json=body, headers=headers)
        await client.aclose()
        return Response(
            content=upstream_resp.content,
            status_code=upstream_resp.status_code,
            headers=dict(upstream_resp.headers),
        )
    except Exception as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Upstream proxy failed: {exc}")


@proxy_app.post("/v1/messages")
async def proxy_anthropic_messages(request: Request) -> Response:
    """Proxy Anthropic messages with transparent compression."""
    body = await request.json()
    upstream_url = os.getenv("SHORTBRAID_ANTHROPIC_URL", "https://api.anthropic.com/v1/messages")
    api_key = request.headers.get("x-api-key") or os.getenv("ANTHROPIC_API_KEY", "")

    messages = body.get("messages", [])
    model = body.get("model", "claude-3-5-sonnet-20241022")
    stream = body.get("stream", False)

    compressed_res = compress(messages, model=model)
    body["messages"] = compressed_res.messages

    _STATS["total_requests"] += 1
    _STATS["total_original_tokens"] += compressed_res.original_tokens
    _STATS["total_compressed_tokens"] += compressed_res.compressed_tokens
    _STATS["total_tokens_saved"] += compressed_res.tokens_saved

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
    }

    client = httpx.AsyncClient(timeout=120.0)

    if stream:
        async def stream_generator() -> AsyncIterator[bytes]:
            try:
                async with client.stream("POST", upstream_url, json=body, headers=headers) as upstream_resp:
                    async for chunk in upstream_resp.aiter_bytes():
                        yield chunk
            finally:
                await client.aclose()

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    try:
        upstream_resp = await client.post(upstream_url, json=body, headers=headers)
        await client.aclose()
        return Response(
            content=upstream_resp.content,
            status_code=upstream_resp.status_code,
            headers=dict(upstream_resp.headers),
        )
    except Exception as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Upstream proxy failed: {exc}")


def run_proxy(host: str = "127.0.0.1", port: int = 8000, upstream: str = "") -> None:
    """Run the proxy server."""
    if upstream:
        os.environ["SHORTBRAID_UPSTREAM_URL"] = upstream
    print(f"🚀 ShortBraid Transparent Proxy listening on http://{host}:{port}")
    print(f"📡 Forwarding to: {os.getenv('SHORTBRAID_UPSTREAM_URL', 'https://api.openai.com/v1/chat/completions')}")
    uvicorn.run(proxy_app, host=host, port=port, log_level="info")
