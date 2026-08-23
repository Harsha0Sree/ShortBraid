"""
Cache Optimization & Prefix Stabilization.

Preserves static prefixes (system prompt, early turns, tool definitions)
so provider KV caches (OpenAI, Anthropic, DeepSeek) hit consistently,
preserving the 90% read discount.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


class PrefixCacheStabilizer:
    """
    Tracks and stabilizes message prefixes across conversation turns.

    Prompt caching requires identical byte-for-byte prefix tokens.
    This class ensures that dynamic compression does not perturb
    already-cached static prefixes.
    """

    def __init__(self, frozen_prefix_count: int = 1):
        self.frozen_prefix_count = frozen_prefix_count
        self._prefix_hashes: list[str] = []

    def compute_prefix_hash(self, messages: list[dict[str, Any]]) -> str:
        """Compute SHA256 hash of the static prefix messages."""
        if not messages:
            return ""
        prefix = messages[: self.frozen_prefix_count]
        serialized = json.dumps(prefix, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()

    def stabilize(
        self,
        messages: list[dict[str, Any]],
        freeze_system: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Splits messages into (frozen_prefix, dynamic_tail).

        Frozen prefix messages should NOT be aggressively modified to keep
        KV prompt cache hit rate at ~100%.
        """
        if not messages:
            return [], []

        split_idx = 0
        if freeze_system and messages[0].get("role") == "system":
            split_idx = 1

        # Also freeze early turns if configured
        if self.frozen_prefix_count > split_idx and len(messages) > self.frozen_prefix_count:
            split_idx = self.frozen_prefix_count

        return messages[:split_idx], messages[split_idx:]
