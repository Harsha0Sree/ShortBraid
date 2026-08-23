"""
Model Context Protocol (MCP) Server for ShortBraid.

Exposes compression, CCR retrieval, and shared agent memory tools
to MCP-compatible clients (Claude Desktop, Cursor, AI IDEs).
"""

from __future__ import annotations

import json
import sys
from typing import Any

from shortbraid.compressor import compress
from shortbraid.context import SharedContext

_GLOBAL_CONTEXT = SharedContext()
_GLOBAL_CCR_STORE: dict[str, Any] = {}


def handle_mcp_request(req: dict[str, Any]) -> dict[str, Any]:
    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "shortbraid-mcp", "version": "0.2.0"},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "shortbraid_compress",
                        "description": "Compress long tool outputs, logs, diffs, code or text using ShortBraid",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string", "description": "Text or JSON to compress"},
                                "model": {"type": "string", "default": "gpt-4o"},
                            },
                            "required": ["content"],
                        },
                    },
                    {
                        "name": "retrieve_original_text",
                        "description": "Retrieve uncompressed original text for a ShortBraid chunk",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "chunk_id": {"type": "string", "description": "Chunk UUID"},
                            },
                            "required": ["chunk_id"],
                        },
                    },
                    {
                        "name": "shared_context_put",
                        "description": "Store large output in multi-agent shared context",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["key", "value"],
                        },
                    },
                    {
                        "name": "shared_context_get",
                        "description": "Retrieve compressed summary from shared context",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                            },
                            "required": ["key"],
                        },
                    },
                ]
            },
        }

    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        if tool_name == "shortbraid_compress":
            content = args.get("content", "")
            res = compress(content, model=args.get("model", "gpt-4o"))
            for cid, data in res.ccr_registry.items():
                _GLOBAL_CCR_STORE[cid] = data
            compressed_txt = res.messages[0]["content"] if res.messages else ""
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"[ShortBraid: Saved {res.tokens_saved} tokens ({(1.0 - res.compression_ratio):.1%})]\n\n"
                                f"{compressed_txt}"
                            ),
                        }
                    ]
                },
            }

        if tool_name == "retrieve_original_text":
            cid = args.get("chunk_id", "")
            if cid in _GLOBAL_CCR_STORE:
                orig = _GLOBAL_CCR_STORE[cid]["original"]
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": orig}]},
                }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": f"Error: Chunk {cid} not found."}]},
            }

        if tool_name == "shared_context_put":
            k = args.get("key", "")
            v = args.get("value", "")
            _GLOBAL_CONTEXT.put(k, v)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": f"Saved '{k}' to shared context."}]},
            }

        if tool_name == "shared_context_get":
            k = args.get("key", "")
            val = _GLOBAL_CONTEXT.get(k, "Not found")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": str(val)}]},
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method '{method}' not found"},
    }


def run_mcp_stdio() -> None:
    """Run MCP server over standard input/output."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_mcp_request(req)
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        except Exception as exc:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": str(exc)},
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
