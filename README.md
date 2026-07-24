# ShortBraid

``` text
███████╗██╗  ██╗ ██████╗ ██████╗ ████████╗██████╗ ██████╗  █████╗ ██╗██████╗
██╔════╝██║  ██║██╔═══██╗██╔══██╗╚══██╔══╝██╔══██╗██╔══██╗██╔══██╗██║██╔══██╗
███████╗███████║██║   ██║██████╔╝   ██║   ██████╔╝██████╔╝███████║██║██║  ██║
╚════██║██╔══██║██║   ██║██╔══██╗   ██║   ██╔══██╗██╔══██╗██╔══██║██║██║  ██║
███████║██║  ██║╚██████╔╝██║  ██║   ██║   ██████╔╝██║  ██║██║  ██║██║██████╔╝
╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═════╝

          Production ingestion & retrieval platform for LLM applications
```

**Async ingestion · Vector search · CCR retrieval · FastAPI · pgvector ·
Redis · MinIO · OpenAI-compatible**

------------------------------------------------------------------------

## Docs

**Docs · Architecture · API · Deployment · Benchmarks**

------------------------------------------------------------------------

## ShortBraid in action

``` text
50 MB log file
        │
        ▼
  Upload API
        │
        ▼
 Async Worker
        │
 ┌──────────────┐
 │ SmartCrusher │
 └──────────────┘
        │
        ▼
 Embeddings
        │
        ▼
 pgvector
        │
        ▼
 Chat API
        │
        ▼
LLM + CCR Retrieval
```

------------------------------------------------------------------------

## What it does

ShortBraid is a production-ready ingestion and retrieval platform for
LLM applications.

Instead of sending raw documents directly to an LLM, ShortBraid builds a
retrieval layer that can:

-   asynchronously ingest large documents
-   compress redundant content
-   generate vector embeddings
-   perform semantic search
-   retrieve original text on demand (CCR)
-   stream OpenAI-compatible responses
-   cache repeated requests
-   expose production metrics

The result is lower latency, lower token usage, and reversible context
retrieval.

------------------------------------------------------------------------

## Architecture

``` text
Client

        │

 FastAPI Gateway

 ├── API Keys
 ├── Rate Limiter
 ├── Redis Cache
 ├── Chat API
 └── Ingest API

        │

Redis Queue

        │

Worker

 ├── SmartCrusher
 ├── Chunker
 ├── Embeddings
 └── Storage

        │

Postgres + pgvector
MinIO
Redis

        │

OpenAI-compatible LLM
```

------------------------------------------------------------------------

## Get started

``` bash
git clone ...

cp .env.example .env

docker compose up -d

curl http://localhost:8000/health
```

Upload

``` bash
curl \
  -H "Authorization: Bearer sk_..." \
  -F file=@logs.json \
  http://localhost:8000/api/v1/ingest
```

Chat

``` bash
curl \
  http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk_..." \
  -d '{
      "messages":[...],
      "stream":true,
      "use_ccr":true
  }'
```

------------------------------------------------------------------------

## Features

### Async ingestion

Large uploads immediately return **202 Accepted** while background
workers process documents.

### Smart compression

Redundant JSON, repeated logs and unnecessary whitespace are removed
before embedding.

### Semantic retrieval

Vector search powered by pgvector and HNSW indexes.

### Reversible Compression (CCR)

Compressed chunks retain references to original content. The LLM can
request the original document whenever additional context is required.

### OpenAI-compatible API

Drop-in replacement for `/v1/chat/completions`.

Supports:

-   streaming
-   tool calls
-   CCR retrieval
-   caching

### Production observability

Built-in:

-   Prometheus
-   structured logging
-   request metrics
-   latency tracking
-   token accounting

------------------------------------------------------------------------

## Performance

  Operation       Result
  --------------- ---------------
  50 MB ingest    Async (202)
  Vector search   \~2 ms (HNSW)
  Streaming       SSE
  Cache           Redis
  Queue           Redis
  Storage         MinIO
  Embeddings      OpenAI

------------------------------------------------------------------------

## API

  Endpoint                   Purpose
  -------------------------- ------------------
  `/health`                  Health checks
  `/metrics`                 Prometheus
  `/api/v1/ingest`           Upload documents
  `/api/v1/documents/{id}`   Status
  `/v1/chat/completions`     Chat
  `/admin/api-keys`          API keys

------------------------------------------------------------------------

## Technology

-   FastAPI
-   asyncpg
-   pgvector
-   Redis
-   MinIO
-   arq
-   httpx
-   OpenAI
-   Prometheus
-   Docker

------------------------------------------------------------------------

## Why ShortBraid?

Most RAG systems stop at vector search.

ShortBraid adds:

-   asynchronous ingestion
-   reversible compression
-   background processing
-   production observability
-   OpenAI-compatible APIs
-   streaming responses
-   semantic caching
-   cost tracking
-   production deployment

It is designed as infrastructure for production LLM applications rather
than a demo RAG pipeline.

------------------------------------------------------------------------

## Roadmap

-   Hybrid search
-   Multi-tenant support
-   MCP integration
-   Cross-document memory
-   Local embedding models
-   S3 backends
-   Multi-provider LLM routing

------------------------------------------------------------------------

## License

MIT
