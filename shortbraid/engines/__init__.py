"""
ShortBraid specialized compression engines.
"""

from shortbraid.detector import ContentType
from shortbraid.engines.base import BaseEngine, EngineResult, count_tokens
from shortbraid.engines.code_engine import CodeEngine
from shortbraid.engines.diff_engine import DiffEngine
from shortbraid.engines.image_engine import ImageEngine
from shortbraid.engines.json_engine import JsonEngine
from shortbraid.engines.log_engine import LogEngine
from shortbraid.engines.search_engine import SearchEngine
from shortbraid.engines.text_engine import TextEngine

ENGINE_REGISTRY: dict[ContentType, BaseEngine] = {
    ContentType.JSON_ARRAY: JsonEngine(),
    ContentType.BUILD_LOG: LogEngine(),
    ContentType.SOURCE_CODE: CodeEngine(),
    ContentType.SEARCH_RESULTS: SearchEngine(),
    ContentType.GIT_DIFF: DiffEngine(),
    ContentType.PLAIN_TEXT: TextEngine(),
    ContentType.HTML: TextEngine(),
    ContentType.IMAGE: ImageEngine(),
    ContentType.UNKNOWN: TextEngine(),
}

__all__ = [
    "BaseEngine",
    "EngineResult",
    "count_tokens",
    "JsonEngine",
    "LogEngine",
    "CodeEngine",
    "SearchEngine",
    "DiffEngine",
    "TextEngine",
    "ImageEngine",
    "ENGINE_REGISTRY",
]
