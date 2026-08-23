"""
Persistent Hierarchical Memory System (user/session/agent/turn).

Backed by SQLite for standalone zero-dependency persistence,
with support for semantic & keyword retrieval, and automatic compression of old turns.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from shortbraid.detector import SmartContentDetector
from shortbraid.engines import ENGINE_REGISTRY, count_tokens


class Memory:
    """
    Hierarchical memory system across user, session, agent, and turn scopes.

    Usage:
        mem = Memory(db_path="~/.shortbraid/memory.db")
        mem.save(scope="session", key="preferences", value={"theme": "dark"}, user_id="u123")
        results = mem.search(query="preferences", user_id="u123")
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = Path.home() / ".shortbraid"
            base_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(base_dir / "memory.db")

        self.db_path = os.path.expanduser(db_path)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    key TEXT NOT NULL,
                    raw_content TEXT NOT NULL,
                    compressed_content TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    user_id TEXT,
                    session_id TEXT,
                    agent_id TEXT,
                    metadata TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_scope_key ON memories(scope, key);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_user_session ON memories(user_id, session_id);")

    def save(
        self,
        scope: str,
        key: str,
        value: Any,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Save a memory entry with automatic compression."""
        mem_id = str(uuid.uuid4())
        raw_str = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        content_type = SmartContentDetector.detect(value)
        engine = ENGINE_REGISTRY.get(content_type, ENGINE_REGISTRY["plain_text"])
        res = engine.compress(value)
        comp_str = res.content if isinstance(res.content, str) else str(res.content)

        meta_json = json.dumps(metadata or {})
        now = time.time()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memories
                    (id, scope, key, raw_content, compressed_content, content_type,
                     user_id, session_id, agent_id, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mem_id,
                    scope,
                    key,
                    raw_str,
                    comp_str,
                    content_type.value,
                    user_id,
                    session_id,
                    agent_id,
                    meta_json,
                    now,
                    now,
                ),
            )
        return mem_id

    def get(
        self,
        scope: str,
        key: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        compressed: bool = True,
    ) -> Optional[str]:
        """Fetch memory entry by key and scope."""
        query = "SELECT raw_content, compressed_content FROM memories WHERE scope = ? AND key = ?"
        params: list[Any] = [scope, key]

        if user_id:
            query += " AND (user_id = ? OR user_id IS NULL)"
            params.append(user_id)
        if session_id:
            query += " AND (session_id = ? OR session_id IS NULL)"
            params.append(session_id)
        if agent_id:
            query += " AND (agent_id = ? OR agent_id IS NULL)"
            params.append(agent_id)

        query += " ORDER BY updated_at DESC LIMIT 1"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            if not row:
                return None
            return row[1] if compressed else row[0]

    def search(
        self,
        query: str,
        scope: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search memories using keyword / token matching."""
        sql = "SELECT id, scope, key, compressed_content, content_type, metadata, created_at FROM memories WHERE 1=1"
        params: list[Any] = []

        if scope:
            sql += " AND scope = ?"
            params.append(scope)
        if user_id:
            sql += " AND (user_id = ? OR user_id IS NULL)"
            params.append(user_id)
        if session_id:
            sql += " AND (session_id = ? OR session_id IS NULL)"
            params.append(session_id)
        if agent_id:
            sql += " AND (agent_id = ? OR agent_id IS NULL)"
            params.append(agent_id)

        if query:
            keywords = [k.strip().lower() for k in query.split() if len(k.strip()) >= 3]
            if keywords:
                clause = " OR ".join(["LOWER(raw_content) LIKE ?" for _ in keywords] + ["LOWER(key) LIKE ?" for _ in keywords])
                sql += f" AND ({clause})"
                for kw in keywords:
                    params.append(f"%{kw}%")
                for kw in keywords:
                    params.append(f"%{kw}%")

        sql += f" ORDER BY updated_at DESC LIMIT {limit}"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "scope": r[1],
                    "key": r[2],
                    "content": r[3],
                    "content_type": r[4],
                    "metadata": json.loads(r[5] or "{}"),
                    "created_at": r[6],
                }
                for r in rows
            ]
