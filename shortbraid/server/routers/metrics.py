"""
/metrics — Prometheus text exposition (Day 9).

Returns the raw Prometheus text format. Prometheus scrapes this on a 15s interval.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from shortbraid.server.metrics import REGISTRY

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics(response: Response) -> Response:
    response.headers["Content-Type"] = CONTENT_TYPE_LATEST
    body = generate_latest(REGISTRY)
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)
