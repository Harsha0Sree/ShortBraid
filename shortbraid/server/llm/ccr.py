"""
CCR — Reversible Compression State Machine (Day 7).

The LLM operates on CRUSHED text (compact, cheap). When it needs detail lost
during compression, it calls `retrieve_original_text(chunk_id)`. The state
machine intercepts the tool call, fetches the original from Postgres, appends
it to the conversation, and re-invokes the LLM.

Loop termination conditions:
  1. finish_reason == "stop"             → done, return content
  2. finish_reason == "length"            → done, return truncated
  3. finish_reason == "tool_calls" AND
     all tools are retrieve_original_text → continue loop, append tool results
  4. Max iterations exceeded             → stop gracefully (safety)
  5. LLM calls unknown tool              → return tool error to LLM, continue

This is the canonical "agentic loop" — a while loop with a finish state.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator

import asyncpg

from shortbraid.server.db import get_pool
from shortbraid.server.logging_config import get_logger
from shortbraid.server.llm.openai_client import OpenAIError, create_chat_completion
from shortbraid.server.metrics import llm_requests_total

log = get_logger(__name__)

MAX_CCR_ITERATIONS = 5  # Safety: don't let the LLM loop forever


# Tool schema advertised to OpenAI (function-calling JSON schema)
RETRIEVE_ORIGINAL_TEXT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "retrieve_original_text",
        "description": (
            "Retrieve the uncompressed original text for a chunk that was "
            "compressed (crushed) before embedding. Call this when you need "
            "detail that may have been lost during compression: exact "
            "timestamps, full JSON keys, log boilerplate, original formatting."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chunk_id": {
                    "type": "string",
                    "description": "UUID of the chunk to retrieve.",
                },
            },
            "required": ["chunk_id"],
        },
    },
}


CCR_TOOLS = [RETRIEVE_ORIGINAL_TEXT_TOOL]


async def _fetch_original_text(chunk_id: str) -> str:
    """Resolve chunk_id → original_text from Postgres or MinIO object storage."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT c.original_text, c.raw_text, d.minio_object
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.id = $1
            """,
            uuid.UUID(chunk_id),
        )
    if row is None:
        return f"[ERROR] chunk {chunk_id} not found"

    # 1. Prefer original_text stored on chunk
    if row["original_text"]:
        return row["original_text"]

    # 2. Fallback to MinIO raw document
    if row["minio_object"]:
        try:
            from shortbraid.server.minio_client import get_object

            s3_uri = row["minio_object"]
            _, _, key = s3_uri.replace("s3://", "").partition("/")
            raw_bytes = get_object(key)
            return raw_bytes.decode("utf-8", errors="replace")
        except Exception as exc:
            log.warning("minio_fetch_fallback_failed", chunk_id=chunk_id, error=str(exc))

    # 3. Fall back to raw_text (crushed) if uncompressed original is unavailable
    return row["raw_text"] or ""


async def execute_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    """Dispatch a tool call. Returns the string result for the LLM."""
    if tool_name == "retrieve_original_text":
        chunk_id = arguments.get("chunk_id", "")
        try:
            return await _fetch_original_text(chunk_id)
        except (ValueError, asyncpg.PostgresError) as exc:
            log.error("tool_fetch_failed", chunk_id=chunk_id, error=str(exc))
            return f"[ERROR] could not fetch chunk {chunk_id}: {exc}"
    return f"[ERROR] unknown tool: {tool_name}"


async def run_ccr_loop(
    system_prompt: str,
    user_query: str,
    context_chunks: list[dict[str, Any]],
    stream: bool = False,
) -> Any:
    """
    Run the CCR agentic loop.

    Args:
        system_prompt:  System instructions.
        user_query:     The user's question.
        context_chunks: List of {"chunk_id": str, "crushed_text": str, "score": float}
                         — these are pre-retrieved from vector search.
        stream:         If True, yields SSE strings from OpenAI for the FINAL
                        (post-tool-call) response.

    Returns:
        If stream=False: dict with final content, iterations, tool_calls_made.
        If stream=True:  AsyncIterator[str] of SSE chunks.
    """
    # Build the initial context message — crushed (compressed) chunks
    context_block = (
        "\n\n".join(
            f"[chunk_id={c['chunk_id']} | score={c.get('score', 0):.3f}]\n{c['crushed_text']}"
            for c in context_chunks
        )
        or "(no context chunks retrieved)"
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Context (compressed via CCR — call retrieve_original_text "
                f"if you need exact detail):\n\n{context_block}\n\n"
                f"Question: {user_query}"
            ),
        },
    ]

    iterations = 0
    tool_calls_made = 0

    while iterations < MAX_CCR_ITERATIONS:
        iterations += 1
        log.info("ccr_iteration", n=iterations, messages=len(messages))

        try:
            resp = await create_chat_completion(
                messages=messages,
                tools=CCR_TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
        except OpenAIError as exc:
            log.error("ccr_openai_failed", error=str(exc), iteration=iterations)
            return {
                "content": f"[CCR error] {exc}",
                "iterations": iterations,
                "tool_calls_made": tool_calls_made,
            }

        llm_requests_total.labels(model="ccr", endpoint="ccr_loop").inc()
        choice = resp["choices"][0]
        msg = choice["message"]
        finish = choice.get("finish_reason")

        # Append the assistant message to history (preserves tool_call ids)
        messages.append(msg)

        # --- Termination: stop or length ---
        if finish in ("stop", "length") or not msg.get("tool_calls"):
            content = msg.get("content") or ""
            if stream:

                async def _final_stream() -> AsyncIterator[str]:
                    chunk_payload = {
                        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
                        "object": "chat.completion.chunk",
                        "choices": [
                            {"index": 0, "delta": {"content": content}, "finish_reason": "stop"}
                        ],
                    }
                    yield f"data: {json.dumps(chunk_payload)}\n\n"
                    yield "data: [DONE]\n\n"

                return _final_stream()

            return {
                "content": content,
                "iterations": iterations,
                "tool_calls_made": tool_calls_made,
                "finish_reason": finish,
            }

        # --- Tool calls ---
        for tc in msg["tool_calls"]:
            tool_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}

            log.info("ccr_tool_call", tool=tool_name, args=args, iteration=iterations)
            tool_calls_made += 1
            result = await execute_tool(tool_name, args)
            log.info(
                "ccr_tool_result",
                tool=tool_name,
                result_len=len(result),
                iteration=iterations,
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                }
            )
        # Loop continues — re-call the LLM with tool results

    # Safety: max iterations exceeded
    log.warning("ccr_max_iterations", n=iterations)
    return {
        "content": "[CCR] Max iterations reached without a final answer.",
        "iterations": iterations,
        "tool_calls_made": tool_calls_made,
    }
