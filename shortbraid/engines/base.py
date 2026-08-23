"""
Base Engine interface and token counting utilities.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from shortbraid.detector import ContentType

try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str | Any) -> int:
        if not text:
            return 0
        if not isinstance(text, str):
            text = str(text)
        try:
            return len(_ENC.encode(text, disallowed_special=()))
        except Exception:
            return max(1, len(text) // 4)

except ImportError:
    # Heuristic: ~4 chars per token for English/code/JSON
    def count_tokens(text: str | Any) -> int:
        if not text:
            return 0
        if not isinstance(text, str):
            text = str(text)
        # Average English/code/json token is 3.8 to 4.2 characters
        return max(1, int(len(text) / 3.8))


@dataclass
class EngineResult:
    content: Any
    original_tokens: int
    compressed_tokens: int
    tokens_saved: int
    compression_ratio: float
    content_type: ContentType
    original_len: int = 0
    compressed_len: int = 0
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    original_sha256: str = ""
    compressed_sha256: str = ""
    uncompressed_original: Optional[Any] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseEngine:
    """Base class for all specialized compression engines."""

    name: str = "base"
    content_type: ContentType = ContentType.PLAIN_TEXT

    def compress(self, content: Any, **kwargs) -> EngineResult:
        raise NotImplementedError
