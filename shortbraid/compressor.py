"""
Core ShortBraid Compressor API.

Provides the canonical Python interface:
    from shortbraid import compress

    result = compress(messages, model="gpt-4o")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=result.messages,
    )
    print(f"Saved {result.tokens_saved} tokens ({result.compression_ratio:.0%})")
"""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from shortbraid.cache import PrefixCacheStabilizer
from shortbraid.detector import ContentType, SmartContentDetector
from shortbraid.engines import ENGINE_REGISTRY, count_tokens


@dataclass
class CompressResult:
    messages: list[dict[str, Any]]
    tokens_saved: int
    compression_ratio: float
    original_tokens: int
    compressed_tokens: int
    content_types_detected: list[str] = field(default_factory=list)
    details: list[dict[str, Any]] = field(default_factory=list)
    ccr_registry: dict[str, Any] = field(default_factory=dict)
    retrieval_tool_schema: Optional[dict[str, Any]] = None

    def __repr__(self) -> str:
        pct = (1.0 - self.compression_ratio) * 100
        return (
            f"<CompressResult: saved={self.tokens_saved} tokens "
            f"({pct:.1f}% reduction) | {self.original_tokens} → {self.compressed_tokens} tokens>"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": self.messages,
            "tokens_saved": self.tokens_saved,
            "compression_ratio": self.compression_ratio,
            "original_tokens": self.original_tokens,
            "compressed_tokens": self.compressed_tokens,
            "content_types_detected": self.content_types_detected,
            "details": self.details,
            "ccr_chunks_count": len(self.ccr_registry),
        }


# CCR Retrieval Tool Schema for OpenAI / Anthropic function calling
CCR_RETRIEVAL_TOOL = {
    "type": "function",
    "function": {
        "name": "retrieve_original_text",
        "description": (
            "Retrieve uncompressed original text for a context chunk that was compressed by ShortBraid. "
            "Call this when exact uncompressed details (full JSON keys, precise timestamps, all log lines) are needed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chunk_id": {
                    "type": "string",
                    "description": "The UUID of the chunk to retrieve.",
                },
            },
            "required": ["chunk_id"],
        },
    },
}


def _calc_content_tokens(content: Any) -> int:
    if not content:
        return 0
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "image_url" or "image_url" in block:
                    img_data = block.get("image_url")
                    detail = img_data.get("detail", "auto") if isinstance(img_data, dict) else "auto"
                    total += 1105 if detail == "high" else 85
                elif block.get("type") == "text":
                    total += count_tokens(block.get("text", ""))
                else:
                    total += count_tokens(str(block))
            else:
                total += count_tokens(str(block))
        return total
    return count_tokens(content)


def compress(
    messages: Union[list[dict[str, Any]], str, dict[str, Any]],
    model: str = "gpt-4o",
    ccr: bool = True,
    preserve_prefix: bool = True,
    collapse_code: bool = False,
    sample_limit: int = 3,
    **kwargs: Any,
) -> CompressResult:
    """
    Compress LLM messages across all content types using ShortBraid's smart routing.

    Args:
        messages: A single string, a single message dict, or a list of message dicts.
        model: Target model name (e.g. "gpt-4o", "claude-3-5-sonnet", etc.)
        ccr: If True, stores uncompressed originals in CCR registry with retrieval tool support.
        preserve_prefix: If True, preserves system message byte-for-byte to maximize KV-cache hits.
        collapse_code: If True, enables AST code compression (collapsing method bodies).
        sample_limit: Number of sample items to keep in JSON arrays.

    Returns:
        CompressResult with compressed messages, token accounting, and CCR metadata.
    """
    # Normalize input
    is_single_string = False
    if isinstance(messages, str):
        is_single_string = True
        normalized_messages = [{"role": "user", "content": messages}]
    elif isinstance(messages, dict):
        normalized_messages = [messages]
    elif isinstance(messages, list):
        normalized_messages = copy.deepcopy(messages)
    else:
        normalized_messages = [{"role": "user", "content": str(messages)}]

    if not normalized_messages:
        return CompressResult(
            messages=[],
            tokens_saved=0,
            compression_ratio=1.0,
            original_tokens=0,
            compressed_tokens=0,
        )

    # Prefix cache stabilizer
    stabilizer = PrefixCacheStabilizer()
    frozen_prefix, dynamic_tail = (
        stabilizer.stabilize(normalized_messages, freeze_system=True)
        if preserve_prefix
        else ([], normalized_messages)
    )

    total_orig_tokens = sum(_calc_content_tokens(m.get("content", "")) for m in normalized_messages)
    processed_messages: list[dict[str, Any]] = []
    ccr_registry: dict[str, Any] = {}
    detected_types: list[str] = []
    details: list[dict[str, Any]] = []

    # 1. Add frozen prefix unchanged
    for msg in frozen_prefix:
        processed_messages.append(msg)
        details.append(
            {
                "role": msg.get("role"),
                "status": "frozen_prefix",
                "content_type": "system",
                "tokens": _calc_content_tokens(msg.get("content", "")),
            }
        )

    # 2. Process dynamic messages through Smart Content Detectors & Specialized Engines
    for msg in dynamic_tail:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Handle tool call arguments or multimodal contents
        if isinstance(content, list):
            compressed_blocks = []
            block_orig = _calc_content_tokens(content)
            for block in content:
                if isinstance(block, dict) and (block.get("type") == "image_url" or "image_url" in block):
                    img_engine = ENGINE_REGISTRY[ContentType.IMAGE]
                    res = img_engine.compress(block)
                    compressed_blocks.append(res.content)
                    detected_types.append("image")
                elif isinstance(block, dict) and block.get("type") == "text":
                    txt = block.get("text", "")
                    ctype = SmartContentDetector.detect(txt)
                    engine = ENGINE_REGISTRY.get(ctype, ENGINE_REGISTRY[ContentType.PLAIN_TEXT])
                    res = engine.compress(txt, collapse_bodies=collapse_code, sample_limit=sample_limit)
                    compressed_blocks.append({"type": "text", "text": str(res.content)})
                    detected_types.append(ctype.value)
                else:
                    compressed_blocks.append(block)

            new_msg = dict(msg)
            new_msg["content"] = compressed_blocks
            processed_messages.append(new_msg)

            block_comp = _calc_content_tokens(compressed_blocks)
            details.append(
                {
                    "role": role,
                    "content_type": "multimodal",
                    "original_tokens": block_orig,
                    "compressed_tokens": block_comp,
                    "tokens_saved": max(0, block_orig - block_comp),
                    "compression_ratio": (block_comp / block_orig) if block_orig > 0 else 1.0,
                }
            )
            continue

        if not isinstance(content, str):
            content = str(content) if content is not None else ""

        if not content.strip():
            processed_messages.append(msg)
            continue

        # Detect content type
        content_type = SmartContentDetector.detect(content)
        detected_types.append(content_type.value)

        # Select Engine
        engine = ENGINE_REGISTRY.get(content_type, ENGINE_REGISTRY[ContentType.PLAIN_TEXT])

        # Execute compression
        engine_res = engine.compress(
            content,
            collapse_bodies=collapse_code,
            sample_limit=sample_limit,
            **kwargs,
        )

        compressed_text = engine_res.content if isinstance(engine_res.content, str) else json.dumps(engine_res.content, ensure_ascii=False)

        # Lossless CCR annotation
        chunk_id = str(uuid.uuid4())
        if ccr and engine_res.tokens_saved > 0:
            ccr_registry[chunk_id] = {
                "original": content,
                "content_type": content_type.value,
                "original_tokens": engine_res.original_tokens,
                "compressed_tokens": engine_res.compressed_tokens,
            }
            # Optional chunk header for LLM reference
            # compressed_text = f"[ShortBraid chunk_id={chunk_id}]\n{compressed_text}"

        new_msg = dict(msg)
        new_msg["content"] = compressed_text
        processed_messages.append(new_msg)

        details.append(
            {
                "role": role,
                "content_type": content_type.value,
                "original_tokens": engine_res.original_tokens,
                "compressed_tokens": engine_res.compressed_tokens,
                "tokens_saved": engine_res.tokens_saved,
                "compression_ratio": engine_res.compression_ratio,
                "chunk_id": chunk_id if ccr else None,
            }
        )

    total_comp_tokens = sum(_calc_content_tokens(m.get("content", "")) for m in processed_messages)
    tokens_saved = max(0, total_orig_tokens - total_comp_tokens)
    ratio = (total_comp_tokens / total_orig_tokens) if total_orig_tokens > 0 else 1.0

    return CompressResult(
        messages=processed_messages,
        tokens_saved=tokens_saved,
        compression_ratio=ratio,
        original_tokens=total_orig_tokens,
        compressed_tokens=total_comp_tokens,
        content_types_detected=list(set(detected_types)),
        details=details,
        ccr_registry=ccr_registry,
        retrieval_tool_schema=CCR_RETRIEVAL_TOOL if ccr else None,
    )
