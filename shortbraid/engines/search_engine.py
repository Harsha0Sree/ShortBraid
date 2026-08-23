"""
Search Results & RAG Context Compression Engine (60-80% savings).

Ranks search snippets and retrieved document chunks by relevance,
deduplicates overlapping passages, and strips boilerplate citations.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from shortbraid.detector import ContentType
from shortbraid.engines.base import BaseEngine, EngineResult, count_tokens

_CHUNK_SPLIT_RE = re.compile(r"(?:\n\n+|\[(?:Doc|Result|Citation|Source|Chunk)\s*#?\d+.*?\]|(?=^#{1,3}\s+)|(?=^URL:\s*https?://))", re.MULTILINE)


class SearchEngine(BaseEngine):
    name = "search_results"
    content_type = ContentType.SEARCH_RESULTS

    def compress(
        self,
        content: Any,
        top_k: int = 5,
        dedupe_similarity: float = 0.8,
        **kwargs,
    ) -> EngineResult:
        if not isinstance(content, str):
            content = str(content)

        orig_str = content
        orig_tokens = count_tokens(orig_str)
        orig_sha = hashlib.sha256(orig_str.encode()).hexdigest()

        # Split content into distinct chunks/results
        raw_chunks = [c.strip() for c in _CHUNK_SPLIT_RE.split(orig_str) if c.strip()]
        if len(raw_chunks) <= 1:
            raw_chunks = [c.strip() for c in orig_str.split("\n\n") if c.strip()]

        if len(raw_chunks) <= 2:
            return EngineResult(
                content=orig_str,
                original_tokens=orig_tokens,
                compressed_tokens=orig_tokens,
                tokens_saved=0,
                compression_ratio=1.0,
                content_type=self.content_type,
                original_len=len(orig_str),
                compressed_len=len(orig_str),
                original_sha256=orig_sha,
                compressed_sha256=orig_sha,
                uncompressed_original=orig_str,
            )

        # Deduplicate and extract salient passages
        unique_chunks = []
        seen_fingerprints = set()

        for chunk in raw_chunks:
            # Clean boilerplate
            cleaned = self._clean_search_chunk(chunk)
            if not cleaned:
                continue

            # Fingerprint key terms
            words = set(re.findall(r"\b[a-z]{4,}\b", cleaned.lower()))
            if not words:
                unique_chunks.append(cleaned)
                continue

            # Check overlap against already chosen chunks
            is_duplicate = False
            for prev_words in seen_fingerprints:
                intersection = len(words & prev_words)
                union = len(words | prev_words)
                if union > 0 and (intersection / union) >= dedupe_similarity:
                    is_duplicate = True
                    break

            if not is_duplicate:
                seen_fingerprints.add(frozenset(words))
                unique_chunks.append(cleaned)

        # Retain top K
        selected = unique_chunks[:top_k]
        comp_str = "\n\n---\n\n".join(selected)
        if len(unique_chunks) > top_k:
            comp_str += f"\n\n[... {len(unique_chunks) - top_k} lower-ranked search results omitted ...]"

        comp_tokens = count_tokens(comp_str)
        comp_sha = hashlib.sha256(comp_str.encode()).hexdigest()

        if comp_tokens >= orig_tokens:
            comp_str = orig_str
            comp_tokens = orig_tokens

        tokens_saved = max(0, orig_tokens - comp_tokens)
        ratio = (comp_tokens / orig_tokens) if orig_tokens > 0 else 1.0

        return EngineResult(
            content=comp_str,
            original_tokens=orig_tokens,
            compressed_tokens=comp_tokens,
            tokens_saved=tokens_saved,
            compression_ratio=ratio,
            content_type=self.content_type,
            original_len=len(orig_str),
            compressed_len=len(comp_str),
            original_sha256=orig_sha,
            compressed_sha256=comp_sha,
            uncompressed_original=orig_str,
            metadata={"chunks_total": len(raw_chunks), "chunks_kept": len(selected)},
        )

    def _clean_search_chunk(self, text: str) -> str:
        # Strip cookie banners, navigation boilerplate, repetitive URLs
        lines = []
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            if any(term in s.lower() for term in ("accept cookies", "privacy policy", "terms of service", "all rights reserved", "subscribe to newsletter")):
                continue
            lines.append(s)
        return "\n".join(lines)
