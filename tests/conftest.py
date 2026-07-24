"""Shared test fixtures."""

import asyncio
import os
import sys

import pytest

# Make app importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def app():
    from app.main import app

    return app
