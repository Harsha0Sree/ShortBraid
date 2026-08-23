"""
Crusher Adapter — Bridges server workers to ShortBraid's multi-engine compression core.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from shortbraid.compressor import compress


@dataclass
class CrushResult:
    crushed: str
    crushed_sha256: str
    original_sha256: str
    original_len: int
    crushed_len: int
    compression_ratio: float  # crushed_len / original_len (lower is better)


def crush(raw: str) -> CrushResult:
    """Apply ShortBraid's smart compression core to raw document text."""
    if not raw:
        empty_sha = hashlib.sha256(b"").hexdigest()
        return CrushResult(
            crushed="",
            crushed_sha256=empty_sha,
            original_sha256=empty_sha,
            original_len=0,
            crushed_len=0,
            compression_ratio=0.0,
        )

    orig_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    orig_len = len(raw)

    result = compress(raw)
    crushed_text = result.messages[0]["content"] if result.messages else ""
    if not isinstance(crushed_text, str):
        crushed_text = str(crushed_text)

    crushed_sha = hashlib.sha256(crushed_text.encode("utf-8")).hexdigest()
    crushed_len = len(crushed_text)
    ratio = (crushed_len / orig_len) if orig_len > 0 else 1.0

    return CrushResult(
        crushed=crushed_text,
        crushed_sha256=crushed_sha,
        original_sha256=orig_sha,
        original_len=orig_len,
        crushed_len=crushed_len,
        compression_ratio=ratio,
    )


def chunk_text(text: str, max_chars: int = 4000, overlap: int = 200) -> list[str]:
    """
    Split text into overlapping chunks for embedding.
    Each chunk <= max_chars; overlap preserves cross-boundary context.
    """
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks
