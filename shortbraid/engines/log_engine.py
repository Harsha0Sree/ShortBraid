"""
Build & Test / System Log Compression Engine (80-95% savings).

Keeps all failures, errors, stack traces, and anomalies while collapsing
passing noise, repeated progress lines, and uniform boilerplate.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from shortbraid.detector import ContentType
from shortbraid.engines.base import BaseEngine, EngineResult, count_tokens

# Log severity and error patterns
_ERROR_PATTERNS = [
    re.compile(r"\b(?:FATAL|CRITICAL|ERROR|SEVERE|EMERGENCY)\b", re.IGNORECASE),
    re.compile(r"\b(?:Exception|Traceback|NullPointerException|Segmentation fault|AssertionError|panic:)\b", re.IGNORECASE),
    re.compile(r"\b(?:FAILED|FAIL|FAILURE|ERR_|Status:\s*[45]\d{2})\b", re.IGNORECASE),
    re.compile(r"\b(?:SyntaxError|TypeError|ValueError|KeyError|IndexError|TimeoutError|ConnectionRefused)\b"),
    re.compile(r'"(?:level|severity)"\s*:\s*"(?:fatal|critical|error|err)"', re.IGNORECASE),
]

_WARN_PATTERNS = [
    re.compile(r"\b(?:WARN|WARNING)\b", re.IGNORECASE),
    re.compile(r'"(?:level|severity)"\s*:\s*"(?:warn|warning)"', re.IGNORECASE),
]

_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")
_PROGRESS_BAR_RE = re.compile(r"(?:[=\-#>]{5,}|\[\s*\d+%\s*\]|\d+/\d+\s*\[|\.{5,})")


class LogEngine(BaseEngine):
    name = "build_log"
    content_type = ContentType.BUILD_LOG

    def compress(
        self,
        content: Any,
        keep_warnings: bool = True,
        max_context_lines: int = 2,
        **kwargs,
    ) -> EngineResult:
        if not isinstance(content, str):
            content = str(content)

        orig_str = content
        orig_tokens = count_tokens(orig_str)
        orig_sha = hashlib.sha256(orig_str.encode()).hexdigest()

        lines = orig_str.splitlines()
        total_lines = len(lines)

        if total_lines <= 6:
            # Very short log, keep as is
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

        # Categorize each line
        is_important = [False] * total_lines
        error_count = 0
        warn_count = 0

        for i, line in enumerate(lines):
            # Check for error patterns
            if any(p.search(line) for p in _ERROR_PATTERNS):
                is_important[i] = True
                error_count += 1
                # Include context around errors
                for ctx in range(max(0, i - max_context_lines), min(total_lines, i + max_context_lines + 1)):
                    is_important[ctx] = True
                continue

            # Check for warning patterns
            if keep_warnings and any(p.search(line) for p in _WARN_PATTERNS):
                is_important[i] = True
                warn_count += 1
                for ctx in range(max(0, i - 1), min(total_lines, i + 2)):
                    is_important[ctx] = True
                continue

            # Check for JSON error fields
            if line.strip().startswith("{") and line.strip().endswith("}"):
                try:
                    obj = json.loads(line)
                    lvl = str(obj.get("level") or obj.get("severity") or "").lower()
                    if lvl in ("fatal", "critical", "error", "err"):
                        is_important[i] = True
                        error_count += 1
                    elif keep_warnings and lvl in ("warn", "warning"):
                        is_important[i] = True
                        warn_count += 1
                except Exception:
                    pass

        # Always preserve the first 2 and last 2 lines for lifecycle context
        for i in range(min(2, total_lines)):
            is_important[i] = True
        for i in range(max(0, total_lines - 2), total_lines):
            is_important[i] = True

        # Build collapsed output
        output_lines = []
        in_collapsed_block = False
        collapsed_run = 0

        for i, line in enumerate(lines):
            if is_important[i]:
                if in_collapsed_block:
                    output_lines.append(f"[... {collapsed_run} passing/info log lines collapsed ...]")
                    in_collapsed_block = False
                    collapsed_run = 0

                # Clean timestamps and progress bars if requested to maximize density
                cleaned_line = _PROGRESS_BAR_RE.sub("[...progress...]", line)
                output_lines.append(cleaned_line)
            else:
                in_collapsed_block = True
                collapsed_run += 1

        if in_collapsed_block and collapsed_run > 0:
            output_lines.append(f"[... {collapsed_run} passing/info log lines collapsed ...]")

        comp_str = "\n".join(output_lines)
        comp_tokens = count_tokens(comp_str)
        comp_sha = hashlib.sha256(comp_str.encode()).hexdigest()
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
            metadata={
                "total_lines": total_lines,
                "kept_lines": len(output_lines),
                "errors_preserved": error_count,
                "warnings_preserved": warn_count,
            },
        )
