"""
Git Diff Compression Engine (40-60% savings).

Preserves change hunks, additions, deletions, file headers, and anchor lines
while dropping excessive unchanged context lines.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from shortbraid.detector import ContentType
from shortbraid.engines.base import BaseEngine, EngineResult, count_tokens

_HUNK_HEADER_RE = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@")


class DiffEngine(BaseEngine):
    name = "git_diff"
    content_type = ContentType.GIT_DIFF

    def compress(
        self,
        content: Any,
        context_lines: int = 1,
        **kwargs,
    ) -> EngineResult:
        if not isinstance(content, str):
            content = str(content)

        orig_str = content
        orig_tokens = count_tokens(orig_str)
        orig_sha = hashlib.sha256(orig_str.encode()).hexdigest()

        lines = orig_str.splitlines()
        if len(lines) <= 6:
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

        output_lines = []
        is_hunk = False
        kept_mask = [False] * len(lines)

        for i, line in enumerate(lines):
            # Always keep diff headers and hunk headers
            if (
                line.startswith("diff --git ")
                or line.startswith("index ")
                or line.startswith("--- ")
                or line.startswith("+++ ")
                or line.startswith("new file mode ")
                or line.startswith("deleted file mode ")
                or _HUNK_HEADER_RE.match(line)
            ):
                kept_mask[i] = True
                if _HUNK_HEADER_RE.match(line):
                    is_hunk = True
                continue

            # Keep additions and deletions
            if is_hunk and (line.startswith("+") or line.startswith("-")):
                kept_mask[i] = True
                # Keep immediate context lines around diff
                for ctx in range(max(0, i - context_lines), min(len(lines), i + context_lines + 1)):
                    kept_mask[ctx] = True

        # Assemble compressed diff
        in_collapsed = False
        collapsed_count = 0

        for i, line in enumerate(lines):
            if kept_mask[i]:
                if in_collapsed:
                    output_lines.append(f" ... ({collapsed_count} unchanged context lines omitted) ...")
                    in_collapsed = False
                    collapsed_count = 0
                output_lines.append(line)
            else:
                in_collapsed = True
                collapsed_count += 1

        if in_collapsed and collapsed_count > 0:
            output_lines.append(f" ... ({collapsed_count} unchanged context lines omitted) ...")

        comp_str = "\n".join(output_lines)
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
        )
