"""
Smart Content Detector — High-accuracy content type detection.

Classifies incoming prompt and message content into:
  - json_array (structured tool outputs, JSONL)
  - source_code (Python, JS, TS, Go, Rust, Java, C++, etc.)
  - build_log (pytest, test logs, docker builds, CI/CD, server logs)
  - search_results (search engine snippets, RAG passages)
  - git_diff (unified diffs, patch files)
  - image (data URIs, base64 images, image objects)
  - html (HTML/XML documents)
  - plain_text (prose, natural language)
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any


class ContentType(str, Enum):
    JSON_ARRAY = "json_array"
    SOURCE_CODE = "source_code"
    BUILD_LOG = "build_log"
    SEARCH_RESULTS = "search_results"
    GIT_DIFF = "git_diff"
    IMAGE = "image"
    HTML = "html"
    PLAIN_TEXT = "plain_text"
    UNKNOWN = "unknown"


# Regex patterns for detection
_GIT_DIFF_RE = re.compile(
    r"(^diff\s+--git\s+a/.*?\s+b/|^index\s+[0-9a-f]{7,}\.\.[0-9a-f]{7,}|^--- [ab]/|^\+\+\+ [ab]/|^@@\s+-\d+,\d+\s+\+\d+,\d+\s+@@)",
    re.MULTILINE,
)

_LOG_INDICATORS = [
    re.compile(r"(?:\[(?:INFO|DEBUG|WARN|WARNING|ERROR|FATAL|CRITICAL|TRACE)\]|\b(?:INFO|DEBUG|WARN|WARNING|ERROR|FATAL|CRITICAL|TRACE)\b[:\s|\[])", re.IGNORECASE),
    re.compile(r"\b(?:Traceback \(most recent call last\)|Exception in thread|NullPointerException|AssertionError|FATAL ERROR|Status:\s*[1-5]\d{2})\b", re.IGNORECASE),
    re.compile(r"(?:^\s*\[?\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}|^\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})", re.MULTILINE),
    re.compile(r"(?:tests passed|tests failed|PASSED|FAILED|=== FAILURES ===|=== SHORT TEST SUMMARY ===)", re.IGNORECASE),
    re.compile(r'"(?:level|severity)"\s*:\s*"(?:info|debug|warn|warning|error|fatal)"', re.IGNORECASE),
]

_SEARCH_RAG_PATTERNS = [
    re.compile(r"\[(?:Doc|Result|Citation|Source|Chunk)\s*#?\d+.*?(?:score|url|title)?:?.*?\]", re.IGNORECASE),
    re.compile(r"(?:^URL:\s*https?://|^Title:\s*.+?\n^Snippet:)", re.MULTILINE | re.IGNORECASE),
    re.compile(r"(?:^Search results for:|^Top \d+ results:)", re.MULTILINE | re.IGNORECASE),
]

_CODE_PATTERNS = [
    re.compile(r"(?:^class\s+[A-Za-z0-9_]+(?:\([^\)]*\))?:|^def\s+[A-Za-z0-9_]+\s*\(.*?\)\s*(?:->.*?)?:)", re.MULTILINE),
    re.compile(r"(?:^(?:export\s+)?(?:function|const|let|var|class|interface|type)\s+[A-Za-z0-9_]+.*?[;{]|\bimport\s+.*?from\s+['\"].*?['\"])", re.MULTILINE),
    re.compile(r"(?:^package\s+[a-z0-9_]+;|^public\s+class\s+[A-Za-z0-9_]+|^fn\s+[A-Za-z0-9_]+|func\s+[A-Za-z0-9_]+)", re.MULTILINE),
    re.compile(r"(?:```(?:python|javascript|typescript|js|ts|go|rust|java|cpp|c|ruby|php|sh|bash)\n[\s\S]*?```)", re.IGNORECASE),
]

_HTML_XML_RE = re.compile(r"^\s*<!DOCTYPE html|<html[\s>]|<div[\s>]|<body[\s>]|<\?xml", re.IGNORECASE)

_IMAGE_DATA_URI_RE = re.compile(r"^data:image\/(?:png|jpeg|jpg|webp|gif);base64,", re.IGNORECASE)


class SmartContentDetector:
    """Detects content type with high precision and zero configuration."""

    @classmethod
    def detect(cls, content: Any) -> ContentType:
        """Detect the content type of a given payload."""
        if content is None:
            return ContentType.PLAIN_TEXT

        # If it's a dict or list structure (e.g. tool output, multimodal block)
        if isinstance(content, list):
            if len(content) > 0 and all(isinstance(x, (dict, list)) for x in content):
                return ContentType.JSON_ARRAY
            # Check for multimodal message content block
            if len(content) > 0 and isinstance(content[0], dict) and "type" in content[0]:
                for item in content:
                    if item.get("type") in ("image_url", "image"):
                        return ContentType.IMAGE
            return ContentType.JSON_ARRAY

        if isinstance(content, dict):
            if content.get("type") in ("image_url", "image") or "image_url" in content:
                return ContentType.IMAGE
            # If it has a large array payload
            for k, v in content.items():
                if isinstance(v, list) and len(v) >= 2:
                    return ContentType.JSON_ARRAY
            return ContentType.JSON_ARRAY

        if not isinstance(content, str):
            content = str(content)

        text = content.strip()
        if not text:
            return ContentType.PLAIN_TEXT

        # 1. Check for Image Data URI or URL
        if _IMAGE_DATA_URI_RE.match(text) or (text.startswith("http") and any(text.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"))):
            return ContentType.IMAGE

        # 2. Check for Git Diff
        diff_matches = len(_GIT_DIFF_RE.findall(text))
        if diff_matches >= 2 or text.startswith("diff --git "):
            return ContentType.GIT_DIFF

        # 3. Check for HTML / XML
        if _HTML_XML_RE.search(text[:200]):
            return ContentType.HTML

        # 4. Check for JSON array or JSONL (tool outputs)
        if (text.startswith("[") and text.endswith("]")) or (text.startswith("{") and text.endswith("}")):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return ContentType.JSON_ARRAY
                if isinstance(parsed, dict) and any(isinstance(v, list) and len(v) >= 2 for v in parsed.values()):
                    return ContentType.JSON_ARRAY
            except Exception:
                pass

        # Check JSONL
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) >= 3:
            json_count = 0
            for line in lines[:10]:
                if line.startswith("{") and line.endswith("}"):
                    try:
                        json.loads(line)
                        json_count += 1
                    except Exception:
                        pass
            if json_count >= 3 and json_count >= len(lines[:10]) * 0.7:
                # Could be JSON logs or JSON array tool output
                if any(_LOG_INDICATORS[4].search(line) for line in lines[:5]):
                    return ContentType.BUILD_LOG
                return ContentType.JSON_ARRAY

        # 5. Check for Build / Test / System Logs
        log_hits = sum(1 for pattern in _LOG_INDICATORS if pattern.search(text))
        if log_hits >= 2 or (len(lines) >= 5 and sum(1 for line in lines[:20] if any(p.search(line) for p in _LOG_INDICATORS)) >= 4):
            return ContentType.BUILD_LOG

        # 6. Check for Search / RAG results
        search_hits = sum(1 for pattern in _SEARCH_RAG_PATTERNS if pattern.search(text))
        if search_hits >= 1 or (text.count("http://") + text.count("https://") >= 3 and "score" in text.lower()):
            return ContentType.SEARCH_RESULTS

        # 7. Check for Source Code
        code_hits = sum(1 for pattern in _CODE_PATTERNS if pattern.search(text))
        if code_hits >= 1 or ("```" in text and any(k in text for k in ("def ", "class ", "function ", "import ", "const "))):
            return ContentType.SOURCE_CODE

        # 8. Default to Plain Text
        return ContentType.PLAIN_TEXT
