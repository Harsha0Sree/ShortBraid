"""
Statistical JSON Array & Tool Output Compression Engine (70-90% savings).

Analyzes structured arrays and tool outputs:
  - Identifies schema and field distributions across items.
  - Keeps 100% of error, failure, anomaly, and exception items.
  - Keeps boundary items (first and last).
  - Collapses homogeneous/uniform items into schema summary + representative sample.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from shortbraid.detector import ContentType
from shortbraid.engines.base import BaseEngine, EngineResult, count_tokens


class JsonEngine(BaseEngine):
    name = "json_array"
    content_type = ContentType.JSON_ARRAY

    def compress(
        self,
        content: Any,
        sample_limit: int = 3,
        preserve_anomalies: bool = True,
        **kwargs,
    ) -> EngineResult:
        orig_str = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        orig_tokens = count_tokens(orig_str)
        orig_sha = hashlib.sha256(orig_str.encode()).hexdigest()

        # Parse JSON
        parsed: Any = None
        if isinstance(content, (dict, list)):
            parsed = content
        else:
            try:
                parsed = json.loads(content)
            except Exception:
                # Fallback: line-by-line JSONL
                return self._compress_jsonl(orig_str, orig_tokens, orig_sha)

        if isinstance(parsed, list):
            compressed_data = self._compress_list(parsed, sample_limit, preserve_anomalies)
        elif isinstance(parsed, dict):
            compressed_data = self._compress_dict(parsed, sample_limit, preserve_anomalies)
        else:
            compressed_data = parsed

        comp_str = json.dumps(compressed_data, ensure_ascii=False, separators=(",", ":"))
        comp_tokens = count_tokens(comp_str)
        comp_sha = hashlib.sha256(comp_str.encode()).hexdigest()

        # If compression didn't help (e.g. tiny payload), keep the cleanest representation
        if comp_tokens >= orig_tokens and len(comp_str) >= len(orig_str):
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
            metadata={"items_count": len(parsed) if isinstance(parsed, list) else 1},
        )

    def _is_anomaly(self, item: Any) -> bool:
        """Check if an item represents an anomaly, error, warning, or unusual state."""
        if not isinstance(item, dict):
            return False

        # Status checks
        status = item.get("status") or item.get("statusCode") or item.get("code")
        if status is not None:
            if isinstance(status, int) and (status >= 400 or status < 200):
                return True
            if isinstance(status, str) and status.lower() in ("error", "failed", "failure", "fatal", "warn", "warning", "rejected"):
                return True

        # Error / exception fields
        for err_key in ("error", "errors", "exception", "failed", "fault", "stackTrace", "is_error"):
            if err_key in item and item[err_key]:
                return True

        # Level indicator
        level = item.get("level") or item.get("severity")
        if isinstance(level, str) and level.lower() in ("error", "warn", "warning", "fatal", "critical"):
            return True

        return False

    def _compress_list(self, items: list[Any], sample_limit: int, preserve_anomalies: bool) -> Any:
        total = len(items)
        if total <= sample_limit * 2:
            return items

        # If items are dicts, perform statistical analysis
        if all(isinstance(x, dict) for x in items):
            anomalies = []
            normals = []

            for idx, item in enumerate(items):
                if preserve_anomalies and self._is_anomaly(item):
                    anomalies.append((idx, item))
                else:
                    normals.append((idx, item))

            # Schema discovery across all items
            all_keys = Counter()
            for item in items:
                for k in item.keys():
                    all_keys[k] += 1

            schema_summary = {
                "schema_fields": list(all_keys.keys()),
                "total_items": total,
                "anomalies_detected": len(anomalies),
            }

            # Select representatives:
            # First item, last item, samples, and ALL anomalies
            selected: list[dict[str, Any]] = []
            seen_indices = set()

            # Add first item
            selected.append({"_index": 0, **items[0]})
            seen_indices.add(0)

            # Add all anomalies with their original index
            for idx, item in anomalies:
                if idx not in seen_indices:
                    selected.append({"_index": idx, "_anomaly": True, **item})
                    seen_indices.add(idx)

            # Add samples from normal items if needed
            step = max(1, len(normals) // sample_limit) if normals else 1
            for i in range(0, len(normals), step):
                idx, item = normals[i]
                if idx not in seen_indices and len(seen_indices) < (sample_limit + len(anomalies) + 2):
                    selected.append({"_index": idx, **item})
                    seen_indices.add(idx)

            # Add last item
            if (total - 1) not in seen_indices:
                selected.append({"_index": total - 1, **items[-1]})
                seen_indices.add(total - 1)

            selected.sort(key=lambda x: x.get("_index", 0))

            return {
                "_shortbraid_summary": schema_summary,
                "_collapsed_count": total - len(selected),
                "items": selected,
            }

        # Fallback for list of primitives or mixed items
        return {
            "_total_items": total,
            "_first": items[0],
            "_last": items[-1],
            "_samples": items[1 : min(sample_limit + 1, total - 1)],
            "_collapsed_count": max(0, total - sample_limit - 2),
        }

    def _compress_dict(self, data: dict[str, Any], sample_limit: int, preserve_anomalies: bool) -> dict[str, Any]:
        result = {}
        for k, v in data.items():
            if isinstance(v, list) and len(v) > sample_limit * 2:
                result[k] = self._compress_list(v, sample_limit, preserve_anomalies)
            elif isinstance(v, dict):
                result[k] = self._compress_dict(v, sample_limit, preserve_anomalies)
            else:
                result[k] = v
        return result

    def _compress_jsonl(self, text: str, orig_tokens: int, orig_sha: str) -> EngineResult:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        parsed_items = []
        for line in lines:
            try:
                parsed_items.append(json.loads(line))
            except Exception:
                parsed_items.append({"_raw": line})

        compressed = self._compress_list(parsed_items, sample_limit=3, preserve_anomalies=True)
        comp_str = json.dumps(compressed, ensure_ascii=False)
        comp_tokens = count_tokens(comp_str)
        tokens_saved = max(0, orig_tokens - comp_tokens)

        return EngineResult(
            content=comp_str,
            original_tokens=orig_tokens,
            compressed_tokens=comp_tokens,
            tokens_saved=tokens_saved,
            compression_ratio=comp_tokens / orig_tokens if orig_tokens else 1.0,
            content_type=self.content_type,
            original_len=len(text),
            compressed_len=len(comp_str),
            original_sha256=orig_sha,
            compressed_sha256=hashlib.sha256(comp_str.encode()).hexdigest(),
            uncompressed_original=text,
        )
