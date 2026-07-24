"""Tests for the OpenAI-compatible request schema and route mounting."""

from fastapi.testclient import TestClient


def test_root_endpoint(app):
    """App should boot and expose /"""
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Headroom CCR"
        assert body["health"] == "/health"


def test_health_requires_backing_services(app):
    """/health should return 503 when DB is unavailable (no docker)."""
    with TestClient(app) as client:
        resp = client.get("/health")
        # In CI without postgres, this will be 503; with stack up, 200
        assert resp.status_code in (200, 503)
        body = resp.json()
        assert "db" in body and "redis" in body


def test_ingest_requires_auth(app):
    """POST /api/v1/ingest/ without bearer should be 401."""
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/ingest/",
            json={"content": "test"},
        )
        assert resp.status_code == 401


def test_chat_requires_auth(app):
    """POST /v1/chat/completions without bearer should be 401."""
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 401


def test_metrics_endpoint(app):
    """/metrics should return Prometheus text format."""
    with TestClient(app) as client:
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")
        # Should contain at least one of our metrics
        assert any(
            name in resp.text
            for name in ("api_requests_total", "llm_requests_total", "api_latency_seconds")
        )
