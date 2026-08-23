"""Tests for Ingestion API (seam:ingest_api) — JSON & Multipart File Uploads."""

import io
import uuid
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from shortbraid.server.main import app
from tests.conftest import MockPool, MockRedisPipeline


def test_ingest_json_payload_success(app):
    with TestClient(app) as client:
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "id": uuid.uuid4(),
            "user_id": uuid.uuid4(),
            "name": "test_key",
            "is_active": True,
        }
        mock_pool = MockPool(mock_conn)
        mock_redis = AsyncMock()
        mock_redis.pipeline = lambda: MockRedisPipeline()

        mock_arq = AsyncMock()
        mock_job = AsyncMock()
        mock_job.job_id = "arq-job-123"
        mock_arq.enqueue_job.return_value = mock_job

        with (
            patch("shortbraid.server.auth.get_pool", return_value=mock_pool),
            patch("shortbraid.server.rate_limit.get_redis", return_value=mock_redis),
            patch("shortbraid.server.routers.ingest.get_pool", return_value=mock_pool),
            patch(
                "shortbraid.server.routers.ingest.put_object",
                return_value="s3://shortbraid-ingest/documents/doc1.json",
            ),
            patch("shortbraid.server.routers.ingest.create_pool", return_value=mock_arq),
        ):

            resp = client.post(
                "/api/v1/ingest",
                headers={"Authorization": "Bearer sk_test_12345"},
                json={"content": '{"level":"info","msg":"test event"}', "source": "api_test"},
            )
            assert resp.status_code == 202
            body = resp.json()
            assert body["status"] == "pending"
            assert "document_id" in body
            assert body["minio_object"] == "s3://shortbraid-ingest/documents/doc1.json"


def test_ingest_multipart_file_upload_success(app):
    with TestClient(app) as client:
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "id": uuid.uuid4(),
            "user_id": uuid.uuid4(),
            "name": "test_key",
            "is_active": True,
        }
        mock_pool = MockPool(mock_conn)
        mock_redis = AsyncMock()
        mock_redis.pipeline = lambda: MockRedisPipeline()

        mock_arq = AsyncMock()
        mock_job = AsyncMock()
        mock_job.job_id = "arq-job-file-123"
        mock_arq.enqueue_job.return_value = mock_job

        file_bytes = b'{"timestamp":"2024-01-01T00:00:00Z","msg":"uploaded log file"}'
        files = {"file": ("logs.json", io.BytesIO(file_bytes), "application/json")}

        with (
            patch("shortbraid.server.auth.get_pool", return_value=mock_pool),
            patch("shortbraid.server.rate_limit.get_redis", return_value=mock_redis),
            patch("shortbraid.server.routers.ingest.get_pool", return_value=mock_pool),
            patch(
                "shortbraid.server.routers.ingest.put_object",
                return_value="s3://shortbraid-ingest/documents/file_doc.json",
            ),
            patch("shortbraid.server.routers.ingest.create_pool", return_value=mock_arq),
        ):

            resp = client.post(
                "/api/v1/ingest",
                headers={"Authorization": "Bearer sk_test_12345"},
                files=files,
            )
            assert resp.status_code == 202
            body = resp.json()
            assert body["status"] == "pending"
            assert body["size_bytes"] == len(file_bytes)


def test_get_document_status_and_invalid_uuid(app):
    with TestClient(app) as client:
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "id": uuid.uuid4(),
            "user_id": uuid.uuid4(),
            "name": "test_key",
            "is_active": True,
        }
        mock_pool = MockPool(mock_conn)

        with patch("shortbraid.server.auth.get_pool", return_value=mock_pool):
            # Invalid UUID should return 400
            resp_invalid = client.get(
                "/api/v1/documents/not-a-valid-uuid",
                headers={"Authorization": "Bearer sk_test_12345"},
            )
            assert resp_invalid.status_code == 400
            assert "Invalid" in resp_invalid.json()["detail"]
