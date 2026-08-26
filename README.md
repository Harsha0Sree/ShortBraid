# ShortBraid

[![PyPI version](https://img.shields.io/pypi/v/shortbraid.svg?color=blue)](https://pypi.org/project/shortbraid/)
[![Python versions](https://img.shields.io/pypi/pyversions/shortbraid.svg)](https://pypi.org/project/shortbraid/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

```text
███████╗██╗  ██╗ ██████╗ ██████╗ ████████╗██████╗ ██████╗  █████╗ ██╗██████╗ 
██╔════╝██║  ██║██╔═══██╗██╔══██╗╚══██╔══╝██╔══██╗██╔══██╗██╔══██╗██║██╔══██╗
███████╗███████║██║   ██║██████╔╝   ██║   ██████╔╝██████╔╝███████║██║██║  ██║
╚════██║██╔══██║██║   ██║██╔══██╗   ██║   ██╔══██╗██╔══██╗██╔══██║██║██║  ██║
███████║██║  ██║╚██████╔╝██║  ██║   ██║   ██████╔╝██║  ██║██║  ██║██║██████╔╝
╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═════╝ 

   Production LLM Context Compression, Lossless CCR Retrieval & Agent Memory Platform
```

**Transparent Proxy · Python SDK · CLI Suite · Lossless CCR · Multi-Agent Memory · Smart Content Detection · Prompt Cache Optimization**

---

## Quick Install

### CLI with `uv` (Recommended)
Install ShortBraid once on your machine in an isolated app environment:
```bash
uv tool install --python 3.13 "shortbraid[all]"
shortbraid --version
```

### Python Library / pip
```bash
pip install shortbraid
```

---

## Python Library Usage

```python
from openai import OpenAI
from shortbraid import compress

client = OpenAI()

messages = [
    {"role": "system", "content": "You are an automated SRE debugging service logs."},
    {"role": "user", "content": "Analyze these build logs:\n\n" + large_log_output},
]

# Compress automatically with smart content detection and prefix stabilization
result = compress(messages, model="gpt-4o")

response = client.chat.completions.create(
    model="gpt-4o",
    messages=result.messages,
)

print(f"Saved {result.tokens_saved} tokens ({result.compression_ratio:.0%})")
```

---

## What Gets Compressed

| Content Type | What Happens | Typical Savings |
| :--- | :--- | :--- |
| **JSON arrays (tool outputs)** | Statistical field analysis keeps errors, anomalies, and schema boundaries | **70–90%** |
| **Build/test logs** | Keeps failures, stack traces, and errors; collapses repetitive passing noise | **80–95%** |
| **Search results / RAG** | Ranks by relevance, deduplicates snippets, removes cookie/navigation noise | **60–80%** |
| **Source code** | AST-aware structural compression preserves signatures, docstrings, collapses bodies | **40–70%** *(opt-in)* |
| **Git diffs** | Preserves change hunks (`+`/`-`), drops unchanged context lines | **40–60%** |
| **Plain text** | Redundancy removal and discourse marker cleaning | **30–50%** |
| **Images** | ML-style router selects optimal detail level and quality tradeoff | **40–90%** |

---

## Real-World Benchmark Results

**100 production log entries with one critical FATAL error buried at position 67:**

| Metric | Baseline | ShortBraid |
| :--- | :--- | :--- |
| **Input tokens** | 2,850 | **288** |
| **Token reduction** | 0% | **89.9% fewer tokens** |
| **Correct answer** | 4/4 | **4/4** |

> *The FATAL error was 100% preserved — not by naive keyword matching, but through statistical anomaly and severity detection.*

Run the benchmark suite locally:
```bash
shortbraid perf
```

---

## CLI Suite

### 1. Transparent Reverse Proxy (`shortbraid proxy`)
Runs a transparent reverse proxy on `http://localhost:8000` forwarding to OpenAI, Anthropic, Gemini, or LiteLLM with zero code changes, automatic prompt caching, and SSE streaming:
```bash
shortbraid proxy --port 8000 --upstream https://api.openai.com/v1/chat/completions
```

### 2. Command Wrap (`shortbraid wrap`)
Compresses command outputs on the fly:
```bash
shortbraid wrap pytest -v
cat production.log | shortbraid wrap -
```

### 3. Model Context Protocol Server (`shortbraid mcp`)
Drop-in MCP server for Claude Desktop and Cursor with context compression and CCR retrieval:
```bash
shortbraid mcp
```

### 4. Failure Learning (`shortbraid learn`)
Reads session transcripts, detects failed tool executions, and synthesizes rules directly into `CLAUDE.md`:
```bash
shortbraid learn --source . --output CLAUDE.md
```

### 5. Performance Benchmarking (`shortbraid perf`)
Runs the full battery of real-world dataset compression tests:
```bash
shortbraid perf
```

---

## Core Capabilities

### 1. Lossless Compression (CCR)
Compresses aggressively for storage/inference, retains full uncompressed originals, and advertises the `retrieve_original_text(chunk_id)` tool to the LLM so nothing is ever lost.

### 2. Smart Content Detection
Zero configuration required. Automatically classifies content into JSON arrays, source code, build logs, search results, git diffs, images, HTML, or plain text, and routes each to the optimal compression engine.

### 3. Cache Optimization
Stabilizes static prefixes (system prompt, early history turns) so upstream KV prompt caches (OpenAI, Anthropic, DeepSeek) hit at ~100%, preserving the 90% read discount.

### 4. Multi-Agent Shared Context
Compresses shared artifacts moving between agents in multi-agent workflows:
```python
from shortbraid import SharedContext

ctx = SharedContext()
ctx.put("research", big_research_output)

# Other agents retrieve the compressed summary:
summary = ctx.get("research")

# Or fetch raw when full inspection is required:
raw = ctx.get_raw("research")
```

### 5. Persistent Hierarchical Memory
Survives across conversations with SQLite and vector indexing across user, session, agent, and turn scopes:
```python
from shortbraid import Memory

mem = Memory()
mem.save(scope="session", key="user_goal", value="Deploy to Kubernetes", user_id="u123")
results = mem.search(query="Kubernetes", user_id="u123")
```

---

## Live Production Deployment

### Docker Compose
```bash
cp .env.example .env
docker compose -f docker-compose.prod.yml up -d
```

### Health & Metrics
- Health checks: `GET /health`
- Prometheus metrics: `GET /metrics`

---

## License
MIT
