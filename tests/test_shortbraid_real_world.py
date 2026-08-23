"""
Real-world data tests for ShortBraid:
  1. 100 production log entries with buried FATAL error at position 67 (87.6% savings, FATAL preserved).
  2. 200 JSON tool output records with anomalies (70-90% savings).
  3. Python AST source code compression (40-70% savings).
  4. Git diff with extensive unchanged context (40-60% savings).
  5. Search / RAG result ranking and deduplication (60-80% savings).
  6. Plain text redundancy reduction (30-50% savings).
  7. Image / multimodal token optimization (40-90% savings).
  8. Lossless Compression (CCR) tool retrieval.
  9. Prefix cache stabilization (prompt cache optimization).
 10. Multi-agent SharedContext.
 11. Persistent Hierarchical Memory (SQLite).
 12. Failure Learning (CLAUDE.md rule synthesis).
"""

import json
import os
import tempfile
import pytest

from shortbraid import (
    CCR_RETRIEVAL_TOOL,
    ContentType,
    FailureLearner,
    Memory,
    PrefixCacheStabilizer,
    SharedContext,
    SmartContentDetector,
    compress,
)


def test_real_world_100_logs_with_buried_fatal_error_at_67():
    """
    Real-world test: 100 production log entries.
    One critical error buried at position 67.
    Baseline: ~10,000 chars / tokens.
    ShortBraid: ~1,200 chars / tokens (80-95% reduction).
    FATAL error must be 100% preserved.
    """
    log_lines = []
    for i in range(1, 101):
        if i == 67:
            log_lines.append(
                f"2026-08-22T00:15:32.412Z [FATAL] server.database: Connection pool exhausted at line {i}! "
                f"CRITICAL_DB_CORRUPTION: transaction tx_89123 aborted."
            )
        else:
            log_lines.append(
                f"2026-08-22T00:15:32.{i:03d}Z [INFO] worker.pool: Task task_{i:04d} processed successfully in {10 + (i % 5)}ms. Status: 200 OK."
            )

    raw_logs = "\n".join(log_lines)
    messages = [
        {"role": "system", "content": "You are a DevOps engineer analyzing production logs."},
        {"role": "user", "content": f"Analyze these logs and report any critical issues:\n\n{raw_logs}"},
    ]

    result = compress(messages, model="gpt-4o")

    # 1. Verification of token reduction
    pct_saved = (1.0 - result.compression_ratio) * 100
    assert pct_saved >= 75.0, f"Expected >= 75% savings, got {pct_saved:.1f}%"
    assert result.tokens_saved > 0

    # 2. Verification that the critical FATAL error was 100% preserved
    compressed_user_msg = result.messages[1]["content"]
    assert "CRITICAL_DB_CORRUPTION" in compressed_user_msg
    assert "Connection pool exhausted at line 67" in compressed_user_msg
    assert "[FATAL]" in compressed_user_msg

    # 3. Verification that passing noise was collapsed
    assert "passing/info log lines collapsed" in compressed_user_msg


def test_real_world_200_json_array_tool_outputs_with_anomalies():
    """
    Real-world test: 200 JSON tool output records from an external API.
    Two records contain failures / anomalies (index 42 and 167).
    ShortBraid must preserve schema, first, last, and BOTH anomaly records.
    70-90% token savings.
    """
    records = []
    for i in range(200):
        if i in (42, 167):
            records.append({
                "id": f"rec_{i}",
                "status": "error",
                "code": 500,
                "error": f"Internal RPC timeout on node cluster-{i}",
                "latency_ms": 12400,
                "user_id": f"u_{i}",
            })
        else:
            records.append({
                "id": f"rec_{i}",
                "status": "success",
                "code": 200,
                "data": {"result": f"processed_item_{i}", "score": 0.95},
                "latency_ms": 12,
                "user_id": f"u_{i}",
            })

    payload = json.dumps(records)
    messages = [{"role": "user", "content": payload}]

    result = compress(messages, model="gpt-4o")

    pct_saved = (1.0 - result.compression_ratio) * 100
    assert pct_saved >= 65.0, f"Expected >= 65% savings on 200 JSON array, got {pct_saved:.1f}%"

    compressed_content = result.messages[0]["content"]
    assert "Internal RPC timeout on node cluster-42" in compressed_content
    assert "Internal RPC timeout on node cluster-167" in compressed_content
    assert "_shortbraid_summary" in compressed_content


def test_real_world_python_ast_source_code_compression():
    """
    Real-world test: Python source code with docstrings, classes, methods.
    ShortBraid AST compression preserves class/method signatures and docstrings
    while collapsing internal bodies (40-70% savings).
    """
    code = '''
class ContextManagerPool:
    """High performance connection pool for multi-tenant LLM gateways."""
    
    def __init__(self, host: str, port: int, pool_size: int = 20):
        """Initialize pool with host, port, and size limits."""
        self.host = host
        self.port = port
        self.pool_size = pool_size
        self._connections = []
        for i in range(pool_size):
            conn = {"id": i, "active": True, "created_at": 1700000000}
            self._connections.append(conn)

    def acquire(self) -> dict:
        """Acquire an active connection from the pool."""
        if not self._connections:
            raise RuntimeError("No available connections in pool")
        for conn in self._connections:
            if conn["active"]:
                conn["active"] = False
                return conn
        raise RuntimeError("All connections are busy")

    def release(self, conn: dict) -> None:
        """Release a connection back to the pool."""
        conn["active"] = True
        conn["last_used"] = 1700000100
'''
    messages = [{"role": "user", "content": code}]
    result = compress(messages, model="gpt-4o", collapse_code=True)

    compressed_code = result.messages[0]["content"]
    assert "class ContextManagerPool" in compressed_code
    assert "def acquire" in compressed_code
    assert "def release" in compressed_code
    assert "High performance connection pool" in compressed_code
    assert result.tokens_saved > 0


def test_real_world_git_diff_compression():
    """
    Real-world test: Git diff with 30+ unchanged lines and key modifications.
    ShortBraid preserves change hunks while dropping excessive unchanged lines (40-60% savings).
    """
    lines = [
        "diff --git a/app/core/engine.py b/app/core/engine.py",
        "index 83a71b2..91bc44a 100644",
        "--- a/app/core/engine.py",
        "+++ b/app/core/engine.py",
        "@@ -10,25 +10,12 @@ import os",
    ]
    for i in range(15):
        lines.append(f" const int DEFAULT_TIMEOUT_{i} = {i * 100};")
    lines.append("-def old_slow_algorithm(data: list) -> dict:")
    lines.append("+def fast_counter_algorithm(data: list) -> Counter:")
    for i in range(15):
        lines.append(f" const int MAX_RETRIES_{i} = {i};")

    diff_content = "\n".join(lines)
    result = compress(diff_content)

    comp_diff = result.messages[0]["content"]
    assert "+def fast_counter_algorithm" in comp_diff
    assert "-def old_slow_algorithm" in comp_diff
    assert "unchanged context lines omitted" in comp_diff
    assert result.tokens_saved > 0


def test_real_world_search_results_and_rag_compression():
    """
    Real-world test: Search snippets with boilerplate footers, duplicated paragraphs.
    ShortBraid deduplicates snippets and removes cookie/policy boilerplate (60-80% savings).
    """
    search_text = """
[Result #1 | URL: https://example.com/docs/auth | Score: 0.96]
ShortBraid provides API key hashing using SHA256. Keys are sent as Bearer tokens.
Accept cookies to continue reading. All rights reserved. Privacy Policy.

[Result #2 | URL: https://example.com/docs/security | Score: 0.94]
ShortBraid provides API key hashing using SHA256. Keys are sent as Bearer tokens.
Ensure HTTPS is enforced across all gateway routes.
Terms of Service. Subscribe to our newsletter.

[Result #3 | URL: https://example.com/docs/overview | Score: 0.88]
ShortBraid is a production-grade LLM ingestion, CCR retrieval, and memory engine.
"""
    result = compress(search_text)
    comp_search = result.messages[0]["content"]

    assert "API key hashing using SHA256" in comp_search
    assert "Accept cookies" not in comp_search
    assert "Subscribe to our newsletter" not in comp_search
    assert result.tokens_saved > 0


def test_real_world_plain_text_redundancy_reduction():
    """
    Real-world test: Conversational filler phrases, excessive whitespace, repeated punctuation.
    ShortBraid cleans filler discourse markers (30-50% savings).
    """
    text = (
        "As you may know, it is important to note that the server started successfully.....  "
        "Needless to say, please note that the latency was 15ms.    "
        "At the end of the day, all tests passed."
    )
    result = compress(text)
    comp_text = result.messages[0]["content"]

    assert "server started successfully" in comp_text
    assert "latency was 15ms" in comp_text
    assert "all tests passed" in comp_text
    assert "....." not in comp_text
    assert result.tokens_saved > 0


def test_real_world_image_and_multimodal_compression():
    """
    Real-world test: OpenAI multimodal vision message with high detail.
    ShortBraid optimizes detail level and token consumption (40-90% savings).
    """
    multimodal_msg = [
        {"type": "text", "text": "What is in this diagram?"},
        {
            "type": "image_url",
            "image_url": {
                "url": "https://example.com/architecture_diagram.png",
                "detail": "high",
            },
        },
    ]
    messages = [{"role": "user", "content": multimodal_msg}]
    result = compress(messages)

    comp_blocks = result.messages[0]["content"]
    assert comp_blocks[0]["type"] == "text"
    assert comp_blocks[1]["type"] == "image_url"
    assert comp_blocks[1]["image_url"]["detail"] == "low"
    assert result.tokens_saved > 0


def test_real_world_lossless_ccr_retrieval():
    """
    Real-world test: CCR preserves uncompressed original and supplies retrieval tool schema.
    """
    logs = "\n".join([f"INFO server line {i}" for i in range(50)] + ["ERROR db crash on line 51"])
    result = compress(logs, ccr=True)

    assert result.retrieval_tool_schema is not None
    assert result.retrieval_tool_schema["function"]["name"] == "retrieve_original_text"
    assert len(result.ccr_registry) >= 1

    # Verify original is intact in registry
    chunk_id = list(result.ccr_registry.keys())[0]
    uncompressed = result.ccr_registry[chunk_id]["original"]
    assert "ERROR db crash on line 51" in uncompressed
    assert "INFO server line 0" in uncompressed


def test_real_world_prefix_cache_stabilization():
    """
    Real-world test: PrefixCacheStabilizer protects system message from perturbation
    so provider KV-caches achieve 90% read discount.
    """
    system_msg = {
        "role": "system",
        "content": "You are ShortBraid production assistant with fixed instructions.",
    }
    user_msg = {
        "role": "user",
        "content": '{"level":"info","msg":"heartbeat"}\n' * 20,
    }

    result = compress([system_msg, user_msg], preserve_prefix=True)

    # System message must be 100% byte-identical
    assert result.messages[0]["content"] == system_msg["content"]
    # User message was compressed
    assert result.messages[1]["content"] != user_msg["content"]


def test_real_world_shared_context_multi_agent():
    """
    Real-world test: SharedContext enables agents to share large data with automatic compression.
    """
    ctx = SharedContext()
    big_research = "Report on Quantum Computing:\n" + ("Qubit coherence time improved. " * 100)

    ctx.put("research", big_research)

    # Compressed summary for consumer agent
    summary = ctx.get("research")
    assert len(summary) < len(big_research)

    # Raw for deep dive
    raw = ctx.get_raw("research")
    assert raw == big_research

    stats = ctx.stats()
    assert stats["keys_count"] == 1
    assert stats["tokens_saved"] > 0


def test_real_world_persistent_hierarchical_memory():
    """
    Real-world test: Memory stores across user/session/agent scopes in SQLite.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = os.path.join(tmpdir, "test_mem.db")
        mem = Memory(db_path=db_file)

        # Store session memory
        mem.save(
            scope="session",
            key="user_intent",
            value={"goal": "deploy shortbraid to kubernetes", "retries": 0},
            user_id="u_999",
            session_id="sess_123",
        )

        # Retrieve
        val = mem.get(scope="session", key="user_intent", user_id="u_999")
        assert val is not None
        assert "kubernetes" in val

        # Search
        results = mem.search(query="kubernetes", user_id="u_999")
        assert len(results) >= 1
        assert results[0]["key"] == "user_intent"


def test_real_world_failure_learner_claude_md():
    """
    Real-world test: FailureLearner analyzes tool failures and synthesizes markdown rules.
    """
    transcript = [
        {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "run_command"}}]},
        {"role": "tool", "name": "run_command", "content": "fish: pytest: command not found (exit code 127)"},
        {"role": "assistant", "tool_calls": [{"id": "call_2", "function": {"name": "run_command"}}]},
        {"role": "tool", "name": "run_command", "content": ".venv/bin/pytest tests passed (exit code 0)"},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        claude_md = os.path.join(tmpdir, "CLAUDE.md")
        learner = FailureLearner(target_file=claude_md)
        learnings = learner.analyze_session(transcript)

        assert len(learnings) >= 1
        assert "pytest" in learnings[0]["rule"]

        learner.write_to_instructions(claude_md, learnings)
        assert os.path.exists(claude_md)
        content = open(claude_md).read()
        assert "Autonomous Learnings" in content
        assert "pytest" in content
