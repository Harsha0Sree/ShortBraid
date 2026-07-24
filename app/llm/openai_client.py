"""
OpenAI HTTP client (Day 4, Day 6).

Uses raw httpx.AsyncClient — no openai SDK. This keeps the dependency surface
minimal and forces us to understand the wire protocol.

tenacity wraps calls with exponential backoff for transient errors.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
    RetryError,
)

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)


class OpenAIError(Exception):
    """Raised when OpenAI returns a non-retryable error or retries exhausted."""


class _RetryableHTTPError(Exception):
    """Wrapper for 5xx / 429 we want tenacity to retry on."""


def _build_client(timeout: int = 60) -> httpx.AsyncClient:
    s = get_settings()
    return httpx.AsyncClient(
        base_url=s.openai_base_url,
        headers={
            "Authorization": f"Bearer {s.openai_api_key}",
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(timeout, connect=10.0),
    )


@retry(
    retry=retry_if_exception_type(_RetryableHTTPError),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log(log, "warning"),  # type: ignore[arg-type]
    reraise=True,
)
async def _request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    json_body: dict[str, Any],
) -> httpx.Response:
    """Single retryable HTTP request."""
    try:
        resp = await client.request(method, path, json=json_body)
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
        log.warning("openai_transport_error", error=str(exc))
        raise _RetryableHTTPError(str(exc)) from exc

    # 429 Too Many Requests — backoff
    if resp.status_code == 429:
        log.warning("openai_rate_limited", status=429)
        raise _RetryableHTTPError(f"429: {resp.text[:200]}")
    # 5xx — backoff
    if resp.status_code >= 500:
        log.warning("openai_5xx", status=resp.status_code, body=resp.text[:200])
        raise _RetryableHTTPError(f"{resp.status_code}: {resp.text[:200]}")
    # 4xx other than 429 — do NOT retry
    if resp.status_code >= 400:
        raise OpenAIError(f"OpenAI {resp.status_code}: {resp.text[:500]}")

    return resp


async def create_chat_completion(
    messages: list[dict[str, Any]],
    model: Optional[str] = None,
    temperature: float = 0.2,
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> dict[str, Any]:
    """Non-streaming chat completion. Returns the parsed JSON response."""
    s = get_settings()
    body: dict[str, Any] = {
        "model": model or s.openai_chat_model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
    if max_tokens:
        body["max_tokens"] = max_tokens

    try:
        async with _build_client(s.openai_timeout_seconds) as client:
            resp = await _request(client, "POST", "/chat/completions", body)
            return resp.json()
    except RetryError as exc:  # tenacity exhausted
        raise OpenAIError(f"OpenAI retries exhausted: {exc}") from exc
    except OpenAIError:
        raise
    except Exception as exc:
        raise OpenAIError(f"Unexpected OpenAI error: {exc}") from exc


async def stream_chat_completion(
    messages: list[dict[str, Any]],
    model: Optional[str] = None,
    temperature: float = 0.2,
    tools: Optional[list[dict[str, Any]]] = None,
) -> AsyncIterator[str]:
    """
    Streaming chat completion (Day 6).

    Yields raw SSE chunks (`data: {...}\\n\\n`) suitable for direct passthrough
    via FastAPI's StreamingResponse. The final `data: [DONE]` is also yielded.
    """
    s = get_settings()
    body: dict[str, Any] = {
        "model": model or s.openai_chat_model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if tools:
        body["tools"] = tools

    async with _build_client(s.openai_timeout_seconds) as client:
        # Note: streaming wraps the whole request in a single retry attempt.
        # Retrying mid-stream is complicated (we'd need to discard partial output).
        try:
            async with client.stream("POST", "/chat/completions", json=body) as resp:
                if resp.status_code != 200:
                    body_text = await resp.aread()
                    raise OpenAIError(f"OpenAI stream {resp.status_code}: {body_text[:500]!r}")
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    # Pass through SSE framing unchanged
                    yield line + "\n"
                    if line.strip() == "data: [DONE]":
                        return
        except _RetryableHTTPError as exc:
            raise OpenAIError(f"Stream retryable error: {exc}") from exc


async def create_embedding(text: str, model: Optional[str] = None) -> list[float]:
    """Single embedding. Day 4 deliverable."""
    s = get_settings()
    body = {
        "model": model or s.openai_embed_model,
        "input": text,
        "dimensions": s.embed_dimensions,
    }
    try:
        async with _build_client(s.openai_timeout_seconds) as client:
            resp = await _request(client, "POST", "/embeddings", body)
            data = resp.json()
            return data["data"][0]["embedding"]
    except RetryError as exc:
        raise OpenAIError(f"Embedding retries exhausted: {exc}") from exc
