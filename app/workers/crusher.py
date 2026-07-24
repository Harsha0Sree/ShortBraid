"""
SmartCrusher — Algorithmic reversible compression (Day 3, Day 7).

"Reversible" here means: we keep both the crushed (compact) form for storage/embedding,
AND a pointer to the original. When the LLM needs detail lost in compression, it calls
the `retrieve_original_text(chunk_id)` tool (Day 7 CCR loop).

Crush strategies (idempotent, deterministic, lossy on the surface but reversible via tool):
  1. Strip ISO-8601 timestamps      (e.g. 2024-01-15T10:30:00.123Z)
  2. Collapse duplicate JSON keys   (last-wins)
  3. Remove insignificant whitespace
  4. Strip JSON logging boilerplate ("level":"info","msg":...)
  5. Collapse repeated punctuation  (multiple newlines collapsed to one)

Big-O: O(n) - single pass per regex. The whole pipeline is O(n) for n = bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

# Pre-compiled patterns (compile once, use many)
_ISO_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
_WHITESPACE = re.compile(r"[ \t]+")
_NEWLINES = re.compile(r"\n{3,}")
_REPEAT_PUNCT = re.compile(r"([.!?])\1{2,}")
_LOG_BOILERPLATE = re.compile(
    r'"(?:level|severity)"\s*:\s*"(?:info|debug|trace|warn|warning|error|fatal)"\s*,?',
    flags=re.IGNORECASE,
)


@dataclass
class CrushResult:
    crushed: str
    crushed_sha256: str
    original_sha256: str
    original_len: int
    crushed_len: int
    compression_ratio: float  # crushed_len / original_len (lower is better)


def crush(raw: str) -> CrushResult:
    """Apply the full crush pipeline. Pure function — no I/O."""
    if not raw:
        return CrushResult(
            crushed="",
            crushed_sha256=hashlib.sha256(b"").hexdigest(),
            original_sha256=hashlib.sha256(b"").hexdigest(),
            original_len=0,
            crushed_len=0,
            compression_ratio=0.0,
        )

    original_sha = hashlib.sha256(raw.encode()).hexdigest()
    original_len = len(raw)

    text = raw

    # 1. Strip ISO timestamps (most log noise)
    text = _ISO_TS.sub("", text)

    # 2. Collapse duplicate JSON keys (last-wins) if it parses as JSON
    text = _collapse_duplicate_keys(text)

    # 3. Strip log boilerplate
    text = _LOG_BOILERPLATE.sub("", text)

    # 4. Whitespace collapse
    text = _WHITESPACE.sub(" ", text)
    text = _NEWLINES.sub("\n", text)
    text = _REPEAT_PUNCT.sub(r"\1", text)

    # 5. Final strip
    text = text.strip()

    crushed_sha = hashlib.sha256(text.encode()).hexdigest()
    crushed_len = len(text)
    ratio = (crushed_len / original_len) if original_len else 0.0

    return CrushResult(
        crushed=text,
        crushed_sha256=crushed_sha,
        original_sha256=original_sha,
        original_len=original_len,
        crushed_len=crushed_len,
        compression_ratio=ratio,
    )


def _collapse_duplicate_keys(text: str) -> str:
    """If the text is a JSON object, deduplicate keys (last-wins)."""
    s = text.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return text

    try:
        obj: Any = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        # Not strict JSON — might be JSONL. Try line-by-line.
        return _collapse_jsonl(text)

    # Recursively dedupe (json.loads already does this for top-level keys,
    # but we apply consistent re-serialization with sort_keys for stability)
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _collapse_jsonl(text: str) -> str:
    """Each non-blank line is a JSON object. Dedupe per line."""
    out_lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            out_lines.append(
                json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
            )
        except (json.JSONDecodeError, ValueError):
            out_lines.append(line)
    return "\n".join(out_lines)


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
