"""
SharedContext — Multi-Agent Context Compression.

Enables multiple agents (or subagents) to share large artifacts, research,
and tool outputs without bloating context windows across agent boundaries.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from shortbraid.detector import SmartContentDetector
from shortbraid.engines import ENGINE_REGISTRY, count_tokens


class SharedContext:
    """
    Shared memory context for multi-agent workflows.

    Usage:
        ctx = SharedContext()
        ctx.put("research", big_output)
        summary = ctx.get("research")  # compressed summary
        raw = ctx.get_raw("research")   # exact original data
    """

    def __init__(self, default_compression: bool = True):
        self.default_compression = default_compression
        self._store: dict[str, dict[str, Any]] = {}

    def put(
        self,
        key: str,
        value: Any,
        metadata: Optional[dict[str, Any]] = None,
        compress_now: bool = True,
    ) -> dict[str, Any]:
        """Store an item in shared context with automatic compression."""
        orig_str = value if isinstance(value, str) else str(value)
        orig_tokens = count_tokens(orig_str)

        entry = {
            "key": key,
            "raw": value,
            "raw_str": orig_str,
            "original_tokens": orig_tokens,
            "compressed_str": orig_str,
            "compressed_tokens": orig_tokens,
            "compression_ratio": 1.0,
            "content_type": "plain_text",
            "metadata": metadata or {},
            "created_at": time.time(),
            "updated_at": time.time(),
        }

        if compress_now:
            content_type = SmartContentDetector.detect(value)
            engine = ENGINE_REGISTRY.get(content_type, ENGINE_REGISTRY["plain_text"])
            res = engine.compress(value)
            entry["compressed_str"] = res.content if isinstance(res.content, str) else str(res.content)
            entry["compressed_tokens"] = res.compressed_tokens
            entry["compression_ratio"] = res.compression_ratio
            entry["content_type"] = content_type.value

        self._store[key] = entry
        return entry

    def get(self, key: str, default: Any = None) -> Any:
        """Get the compressed, token-efficient version of the item."""
        if key not in self._store:
            return default
        return self._store[key]["compressed_str"]

    def get_raw(self, key: str, default: Any = None) -> Any:
        """Get the uncompressed original item."""
        if key not in self._store:
            return default
        return self._store[key]["raw"]

    def get_entry(self, key: str) -> Optional[dict[str, Any]]:
        """Get the full metadata entry including token metrics."""
        return self._store.get(key)

    def list_keys(self) -> list[str]:
        """List all stored keys."""
        return list(self._store.keys())

    def clear(self) -> None:
        """Clear all stored items."""
        self._store.clear()

    def stats(self) -> dict[str, Any]:
        """Compute aggregate token savings across all shared items."""
        orig = sum(item["original_tokens"] for item in self._store.values())
        comp = sum(item["compressed_tokens"] for item in self._store.values())
        return {
            "keys_count": len(self._store),
            "original_tokens": orig,
            "compressed_tokens": comp,
            "tokens_saved": max(0, orig - comp),
            "compression_ratio": (comp / orig) if orig > 0 else 1.0,
        }
