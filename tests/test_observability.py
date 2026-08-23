"""Tests for Observability (seam:observability) — Health, Metrics, and In-flight tracking."""

from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from shortbraid.server.main import app
from shortbraid.server.metrics import in_flight_requests
from tests.conftest import MockPool


def test_health_all_ok(app):
    with TestClient(app) as client:
        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = 1
        mock_pool = MockPool(mock_conn)
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True

        with (
            patch("shortbraid.server.db._pool", mock_pool),
            patch("shortbraid.server.redis_client._redis", mock_redis),
            patch("shortbraid.server.minio_client.check_s3_health", return_value=True),
        ):
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["db"] == "ok"
            assert data["redis"] == "ok"
            assert data["minio"] == "ok"


def test_health_degraded_when_minio_down(app):
    with TestClient(app) as client:
        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = 1
        mock_pool = MockPool(mock_conn)
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True

        with (
            patch("shortbraid.server.db._pool", mock_pool),
            patch("shortbraid.server.redis_client._redis", mock_redis),
            patch("shortbraid.server.minio_client.check_s3_health", return_value=False),
        ):
            resp = client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["db"] == "ok"
            assert data["redis"] == "ok"
            assert data["minio"] == "down"


def test_metrics_content_and_in_flight_balance(app):
    with TestClient(app) as client:
        initial_val = (
            in_flight_requests._value.get() if hasattr(in_flight_requests, "_value") else 0
        )
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "api_requests_total" in resp.text
        # In-flight gauge must return back to its baseline after request finishes
        final_val = in_flight_requests._value.get() if hasattr(in_flight_requests, "_value") else 0
        assert final_val == initial_val
