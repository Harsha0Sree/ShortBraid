"""
ShortBraid — Production-grade LLM Context Compression, Reversible Retrieval (CCR),
Transparent Proxy & Agent Memory.
"""

from shortbraid.cache import PrefixCacheStabilizer
from shortbraid.compressor import CCR_RETRIEVAL_TOOL, CompressResult, compress
from shortbraid.context import SharedContext
from shortbraid.detector import ContentType, SmartContentDetector
from shortbraid.engines import (
    ENGINE_REGISTRY,
    BaseEngine,
    CodeEngine,
    DiffEngine,
    EngineResult,
    ImageEngine,
    JsonEngine,
    LogEngine,
    SearchEngine,
    TextEngine,
    count_tokens,
)
from shortbraid.learn import FailureLearner
from shortbraid.memory import Memory

__version__ = "0.2.0"

__all__ = [
    "compress",
    "CompressResult",
    "CCR_RETRIEVAL_TOOL",
    "SharedContext",
    "Memory",
    "FailureLearner",
    "SmartContentDetector",
    "ContentType",
    "PrefixCacheStabilizer",
    "ENGINE_REGISTRY",
    "BaseEngine",
    "EngineResult",
    "JsonEngine",
    "LogEngine",
    "CodeEngine",
    "SearchEngine",
    "DiffEngine",
    "TextEngine",
    "ImageEngine",
    "count_tokens",
    "__version__",
]
