"""Tests for config, auth hashing, cache key derivation."""

import hashlib

from app.auth import generate_api_key
from app.cache import _cache_key
from app.config import get_settings


def test_settings_loads_defaults():
    s = get_settings()
    assert s.app_port == 8000
    assert s.embed_dimensions == 1536
    assert s.postgres_dsn.startswith("postgresql://")


def test_api_key_hash_is_sha256():
    raw, hashed = generate_api_key()
    assert raw.startswith("sk_")
    assert hashed == hashlib.sha256(raw.encode()).hexdigest()
    assert len(hashed) == 64


def test_cache_key_is_stable():
    k1 = _cache_key("hello world", "chat", "ctx-1")
    k2 = _cache_key("hello world", "chat", "ctx-1")
    k3 = _cache_key("hello world", "chat", "ctx-2")
    assert k1 == k2
    assert k1 != k3
    assert k1.startswith("cache:chat:")


def test_cache_key_normalizes_whitespace_and_case():
    k1 = _cache_key("Hello World", "chat", None)
    k2 = _cache_key("hello world", "chat", None)
    k3 = _cache_key("  hello world  ", "chat", None)
    assert k1 == k2 == k3
