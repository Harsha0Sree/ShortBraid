"""Unit and integration tests for Auth & Admin APIs (seam:auth, seam:admin_api)."""

import uuid
import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from shortbraid.server.auth import authenticate, generate_api_key, hash_api_key
from shortbraid.server.main import app


def test_api_key_generation_and_hashing():
    raw, hashed = generate_api_key()
    assert raw.startswith("sk_")
    assert len(hashed) == 64
    assert hash_api_key(raw) == hashed


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
async def test_authenticate_success():
    raw_key = "sk_valid_test_key_12345"
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "name": "test_key",
        "is_active": True,
    }
    mock_pool = MockPool(mock_conn)

    mock_request = AsyncMock()
    mock_request.state = AsyncMock()
    mock_creds = AsyncMock()
    mock_creds.credentials = raw_key

    with patch("shortbraid.server.auth.get_pool", return_value=mock_pool):
        ctx = await authenticate(mock_request, mock_creds)
        assert ctx["name"] == "test_key"
        assert "user_id" in ctx


@pytest.mark.asyncio
async def test_authenticate_revoked_or_missing_fails():
    mock_request = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await authenticate(mock_request, None)
    assert exc_info.value.status_code == 401


def test_admin_create_and_revoke_key_flow(app):
    with TestClient(app) as client:
        # 1. Create key
        user_uuid = str(uuid.uuid4())
        mock_conn = AsyncMock()
        mock_pool = MockPool(mock_conn)

        with patch("shortbraid.server.routers.admin.get_pool", return_value=mock_pool):
            resp = client.post(
                "/admin/api-keys", json={"user_id": user_uuid, "name": "production_key"}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["api_key"].startswith("sk_")
            assert data["name"] == "production_key"
            key_id = data["key_id"]

        # 2. Revoke key
        mock_conn.execute.return_value = "UPDATE 1"
        mock_conn.fetchrow.return_value = {
            "id": uuid.UUID(key_id),
            "user_id": uuid.UUID(user_uuid),
            "name": "production_key",
            "is_active": True,
        }

        with (
            patch("shortbraid.server.auth.get_pool", return_value=mock_pool),
            patch("shortbraid.server.routers.admin.get_pool", return_value=mock_pool),
        ):
            del_resp = client.delete(
                f"/admin/api-keys/{key_id}",
                headers={"Authorization": f"Bearer {data['api_key']}"},
            )
            assert del_resp.status_code == 200
            assert del_resp.json()["ok"] is True
            assert del_resp.json()["revoked_key_id"] == key_id
