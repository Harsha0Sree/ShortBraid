"""
Plain Text Redundancy Reduction Engine (30-50% savings).

Removes repetitive phrasing, excessive whitespace, repeated punctuation,
and filler discourse markers while preserving core semantics.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from shortbraid.detector import ContentType
from shortbraid.engines.base import BaseEngine, EngineResult, count_tokens

_WHITESPACE_RE = re.compile(r"[ \t]+")
_NEWLINES_RE = re.compile(r"\n{3,}")
_REPEAT_PUNCT_RE = re.compile(r"([.!?,-])\1{2,}")
_REPEAT_CHARS_RE = re.compile(r"(.)\1{4,}")

# Filler discourse markers that carry 0 semantic value in LLM context
_FILLER_PHRASES = [
    re.compile(r"\b(?:as you may know|as previously mentioned|it is important to note that|needless to say|at the end of the day|in other words)\b,?", re.IGNORECASE),
    re.compile(r"\b(?:please note that|it should be noted that|for what it's worth|to be completely honest)\b,?", re.IGNORECASE),
]


class TextEngine(BaseEngine):
    name = "plain_text"
    content_type = ContentType.PLAIN_TEXT

    def compress(
        self,
        content: Any,
        dedupe_sentences: bool = True,
        **kwargs,
    ) -> EngineResult:
        if not isinstance(content, str):
            content = str(content)

        orig_str = content
        orig_tokens = count_tokens(orig_str)
        orig_sha = hashlib.sha256(orig_str.encode()).hexdigest()

        text = orig_str

        # 1. Clean repetitive characters and punctuation
        text = _REPEAT_PUNCT_RE.sub(r"\1", text)
        text = _REPEAT_CHARS_RE.sub(r"\1\1\1", text)

        # 2. Strip conversational filler phrases
        for filler in _FILLER_PHRASES:
            text = filler.sub("", text)

        # 3. Deduplicate exact consecutive sentences (both intra-line and multi-line)
        if dedupe_sentences:
            # First, deduplicate consecutive repeated sentences within paragraphs
            text = re.sub(r"([A-Z0-9][^.!?\n]+[.!?]\s*)(?:\1){2,}", r"\1", text)
            lines = text.splitlines()
            cleaned_lines = []
            prev_line = None
            for line in lines:
                s = line.strip()
                if s and s == prev_line:
                    continue
                cleaned_lines.append(line)
                if s:
                    prev_line = s
            text = "\n".join(cleaned_lines)

        # 4. Collapse whitespace
        text = _WHITESPACE_RE.sub(" ", text)
        text = _NEWLINES_RE.sub("\n\n", text)
        text = text.strip()

        comp_tokens = count_tokens(text)
        comp_sha = hashlib.sha256(text.encode()).hexdigest()

        if comp_tokens >= orig_tokens:
            text = orig_str
            comp_tokens = orig_tokens

        tokens_saved = max(0, orig_tokens - comp_tokens)
        ratio = (comp_tokens / orig_tokens) if orig_tokens > 0 else 1.0

        return EngineResult(
            content=text,
            original_tokens=orig_tokens,
            compressed_tokens=comp_tokens,
            tokens_saved=tokens_saved,
            compression_ratio=ratio,
            content_type=self.content_type,
            original_len=len(orig_str),
            compressed_len=len(text),
            original_sha256=orig_sha,
            compressed_sha256=comp_sha,
            uncompressed_original=orig_str,
        )
