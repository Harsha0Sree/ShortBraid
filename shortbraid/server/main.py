"""
FastAPI application entrypoint.

Wires:
  - Lifecycle: init/close pg pool, redis, minio
  - Middleware: request_id, structured logging, metrics
  - Routers: health, ingest, chat, metrics, admin
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

import shortbraid
from shortbraid.server.config import get_settings
from shortbraid.server.db import close_pool, init_pool
from shortbraid.server.logging_config import configure_logging, get_logger
from shortbraid.server.metrics import (
    api_latency_seconds,
    api_requests_total,
    in_flight_requests,
)
from shortbraid.server.minio_client import ensure_bucket_exists, init_s3
from shortbraid.server.redis_client import close_redis, init_redis
from shortbraid.server.routers import admin, chat, health, ingest, metrics as metrics_router

configure_logging()
log = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup/shutdown lifecycle.

    Resilient: if backing services are unavailable at boot, the app still starts
    so /health can report the degraded state and the orchestrator can decide.
    """
    log.info("app_starting", env=settings.app_env, name=settings.app_name)

    pool = None
    redis = None
    try:
        pool = await init_pool()
    except Exception as exc:
        log.error("pg_init_failed_at_boot", error=str(exc))
    try:
        redis = await init_redis()
    except Exception as exc:
        log.error("redis_init_failed_at_boot", error=str(exc))

    try:
        init_s3()
        ensure_bucket_exists()
    except Exception as exc:
        log.error("minio_init_failed_at_boot", error=str(exc))

    app.state.pool = pool
    app.state.redis = redis

    log.info("app_ready", host=settings.app_host, port=settings.app_port)
    yield

    log.info("app_stopping")
    await close_redis()
    await close_pool()
    log.info("app_stopped")


app = FastAPI(
    title="ShortBraid",
    description="Production-grade LLM ingestion & retrieval with Reversible Compression (CCR)",
    version=shortbraid.__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# --- CORS (permissive in dev, tighten in prod) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_prod else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request ID + structured logging middleware ---
class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        started = time.time()
        in_flight_requests.inc()
        try:
            response: Response = await call_next(request)
        except Exception:
            in_flight_requests.dec()
            log.exception("request_failed", path=request.url.path)
            raise

        elapsed_ms = int((time.time() - started) * 1000)
        in_flight_requests.dec()

        # Metrics
        endpoint = request.url.path
        api_requests_total.labels(
            endpoint=endpoint, method=request.method, status=response.status_code
        ).inc()
        api_latency_seconds.labels(endpoint=endpoint, method=request.method).observe(
            elapsed_ms / 1000.0
        )

        response.headers["X-Request-Id"] = request_id
        response.headers["X-Response-Time-ms"] = str(elapsed_ms)

        log.info(
            "request",
            status=response.status_code,
            latency_ms=elapsed_ms,
        )
        return response


app.add_middleware(RequestContextMiddleware)


# --- Routers ---
app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(chat.router)
app.include_router(metrics_router.router)
app.include_router(admin.router)


@app.get("/")
async def root() -> dict:
    return {
        "name": "ShortBraid",
        "version": shortbraid.__version__,
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }
