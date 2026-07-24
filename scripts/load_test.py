"""
Day 10 deliverable — Locust load test for /v1/chat/completions.

Run:
    locust -f scripts/load_test.py --host http://localhost:8000

Then open http://localhost:8089, set:
    - Number of users: 50
    - Ramp-up: 5
    - API key (in Authorization header) below

Document before/after RPS in README.
"""

from __future__ import annotations

import os
import random
import uuid

from locust import HttpUser, between, task

API_KEY = os.environ.get("LOAD_TEST_API_KEY", "sk_replace_me")

QUERIES = [
    "What errors occurred in the last hour?",
    "Summarize the most frequent log patterns.",
    "Find requests with latency above 500ms.",
    "Which user triggered the most 429s?",
    "Show me the timeline of the last incident.",
]


class ChatUser(HttpUser):
    """Simulates a user hitting /v1/chat/completions."""

    wait_time = between(0.5, 2.0)
    host = os.environ.get("LOAD_TEST_HOST", "http://localhost:8000")

    def on_start(self) -> None:
        self.headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid.uuid4()),
        }

    @task(3)
    def chat_non_stream(self) -> None:
        """Non-streaming chat — exercises DB pool + OpenAI client."""
        q = random.choice(QUERIES)
        self.client.post(
            "/v1/chat/completions",
            headers=self.headers,
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": q}],
                "temperature": 0.2,
                "stream": False,
                "use_ccr": False,
            },
            timeout=30,
        )

    @task(1)
    def chat_stream(self) -> None:
        """Streaming chat — exercises SSE path."""
        q = random.choice(QUERIES)
        with self.client.post(
            "/v1/chat/completions",
            headers=self.headers,
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": q}],
                "temperature": 0.2,
                "stream": True,
                "use_ccr": False,
            },
            stream=True,
            timeout=60,
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"status {resp.status_code}")
                return
            # Drain the SSE stream
            bytes_recv = 0
            for chunk in resp.iter_content(chunk_size=1024):
                bytes_recv += len(chunk)
                if bytes_recv > 1_000_000:  # safety
                    break
            resp.success()

    @task(1)
    def health(self) -> None:
        """Lightweight check — exercises DB + Redis ping."""
        self.client.get("/health", name="/health")

    @task(1)
    def ingest(self) -> None:
        """Tiny ingest — exercises MinIO + arq enqueue path."""
        payload = {
            "content": '{"ts":"2024-01-01T12:00:00Z","level":"info","msg":"load test"}',
            "source": "locust",
            "content_type": "application/json",
        }
        self.client.post(
            "/api/v1/ingest/",
            headers=self.headers,
            json=payload,
            timeout=10,
        )
