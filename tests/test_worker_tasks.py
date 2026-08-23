"""Tests for arq worker background tasks (seam:worker_tasks)."""

import uuid
import pytest
from unittest.mock import AsyncMock, patch

from shortbraid.server.workers.tasks import crush_document


class MockAcquireContext:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockPool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return MockAcquireContext(self.conn)


@pytest.mark.asyncio
async def test_crush_document_success():
    doc_id = str(uuid.uuid4())
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": uuid.UUID(doc_id),
        "minio_object": f"s3://shortbraid-ingest/documents/{doc_id}.json",
        "metadata": {},
    }
    mock_pool = MockPool(mock_conn)

    raw_payload = (
        b'{"timestamp":"2024-01-01T00:00:00Z","level":"info","msg":"user logged in","user_id":"u1"}'
    )

    with (
        patch("shortbraid.server.workers.tasks.get_pool", return_value=mock_pool),
        patch("shortbraid.server.workers.tasks.get_object", return_value=raw_payload),
        patch("shortbraid.server.workers.tasks.create_embedding", AsyncMock(return_value=[0.1] * 1536)),
    ):

        result = await crush_document({}, doc_id)
        assert result["ok"] is True
        assert result["chunks_inserted"] >= 1
        assert "compression_ratio" in result

        # Verify SQL status update to embedded
        assert mock_conn.execute.await_count >= 2


@pytest.mark.asyncio
async def test_crush_document_not_found():
    doc_id = str(uuid.uuid4())
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None
    mock_pool = MockPool(mock_conn)

    with patch("shortbraid.server.workers.tasks.get_pool", return_value=mock_pool):
        result = await crush_document({}, doc_id)
        assert result["ok"] is False
        assert result["error"] == "not_found"


@pytest.mark.asyncio
async def test_crush_document_failure_marks_failed():
    doc_id = str(uuid.uuid4())
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": uuid.UUID(doc_id),
        "minio_object": f"s3://shortbraid-ingest/documents/{doc_id}.json",
        "metadata": {},
    }
    mock_pool = MockPool(mock_conn)

    with (
        patch("shortbraid.server.workers.tasks.get_pool", return_value=mock_pool),
        patch("shortbraid.server.workers.tasks.get_object", side_effect=RuntimeError("MinIO connection reset")),
    ):

        result = await crush_document({}, doc_id)
        assert result["ok"] is False
        assert "MinIO connection reset" in result["error"]

        # Ensure document status was updated to failed
        status_updates = [
            call.args[0] for call in mock_conn.execute.await_args_list if len(call.args) > 0
        ]
        assert any("SET status='failed'" in query for query in status_updates)
