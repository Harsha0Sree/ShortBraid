"""
Structured logging with structlog (Day 8).

Emits JSON to stdout with: timestamp, level, event, request_id, user_id,
latency_ms, error, etc. Machine-parseable by ELK / Loki / Datadog.
"""

import logging
import sys

import structlog

from shortbraid.server.config import get_settings


def configure_logging() -> None:
    settings = get_settings()

    # Stdlib root logger — pipe everything to stdout
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level,
    )

    timestamper = structlog.processors.TimeStamper(fmt="iso")

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.is_prod:
        # JSON for production — machine-parseable
        renderer = structlog.processors.JSONRenderer()
    else:
        # Pretty console renderer for dev
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Quiet noisy libs
    for noisy in ("uvicorn.access", "uvicorn.error", "httpx", "asyncpg"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str = "app"):
    return structlog.get_logger(name)
