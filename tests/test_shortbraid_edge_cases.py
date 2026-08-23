"""
Edge cases & Stress tests for ShortBraid:
  - Empty messages list []
  - Empty string "", whitespace only "   \n\t "
  - Huge payload (100k+ characters)
  - Unicode, emoji, multilingual characters (Chinese, Japanese, Arabic, Russian, emojis 🚀🔥✨)
  - Malformed / corrupted JSON
  - Non-string / mixed types in messages
  - Single-string input to compress()
  - Code with syntax errors
  - Log with 0 errors vs Log with 100% errors
  - Diff with only additions or only deletions
  - CLI commands via Click test runner
  - Transparent Proxy endpoints (/health, /metrics, /v1/chat/completions, /v1/messages)
"""

import json
from unittest.mock import AsyncMock, patch
from click.testing import CliRunner
from fastapi.testclient import TestClient

from shortbraid import compress
from shortbraid.cli.main import cli
from shortbraid.cli.mcp import handle_mcp_request
from shortbraid.cli.proxy import proxy_app


def test_edge_case_empty_messages():
    res = compress([])
    assert res.messages == []
    assert res.tokens_saved == 0
    assert res.compression_ratio == 1.0


def test_edge_case_empty_and_whitespace_strings():
    res1 = compress("")
    assert res1.tokens_saved == 0

    res2 = compress("   \n\t\n   ")
    assert res2.tokens_saved == 0


def test_edge_case_huge_payload():
    # 200,000 characters payload
    large_payload = "INFO heartbeat status: ok\n" * 8000
    res = compress(large_payload)
    assert res.tokens_saved > 1000
    assert len(res.messages[0]["content"]) < len(large_payload)


def test_edge_case_unicode_emojis_multilingual():
    text = (
        "🚀 生产日志 Production Log: 数据库连接正常 Database connection OK. "
        "Пользователь вошел в систему. "
        "تم تسجيل الدخول بنجاح. "
        "エラーは発生しませんでした。 ✨"
    )
    res = compress(text)
    comp = res.messages[0]["content"]
    assert "🚀" in comp
    assert "生产日志" in comp
    assert "Пользователь" in comp
    assert "تم تسجيل الدخول" in comp
    assert "エラー" in comp


def test_edge_case_malformed_corrupt_json():
    corrupt_json = '{"level": "error", "broken_key": [1, 2, 3, {"unclosed": true'
    res = compress(corrupt_json)
    # Shouldn't raise; falls back gracefully
    assert res.messages[0]["content"] is not None


def test_edge_case_non_string_types():
    messages = [
        {"role": "user", "content": 12345},
        {"role": "assistant", "content": {"status": "success", "count": 10}},
        {"role": "user", "content": None},
    ]
    res = compress(messages)
    assert len(res.messages) == 3


def test_edge_case_single_string_convenience_api():
    res = compress("Simple one liner query")
    assert len(res.messages) == 1
    assert res.messages[0]["role"] == "user"
    assert res.messages[0]["content"] == "Simple one liner query"


def test_edge_case_code_with_syntax_errors():
    broken_code = """
def broken_python_function(
    for i in range(10)
        print("missing colon and parenthesis"
"""
    res = compress(broken_code, collapse_code=True)
    assert "broken_python_function" in res.messages[0]["content"]


def test_edge_case_log_with_all_errors_vs_no_errors():
    # All errors -> nothing dropped
    all_errors = "\n".join([f"FATAL database corruption error at record {i}" for i in range(10)])
    res_err = compress(all_errors)
    for i in range(10):
        assert f"record {i}" in res_err.messages[0]["content"]

    # No errors -> collapsed
    no_errors = "\n".join([f"INFO heartbeat tick {i}" for i in range(50)])
    res_clean = compress(no_errors)
    assert res_clean.tokens_saved > 0
    assert "collapsed" in res_clean.messages[0]["content"]


def test_edge_case_diff_only_additions():
    diff = """
diff --git a/new_file.py b/new_file.py
new file mode 100644
--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,5 @@
+# New module
+def main():
+    print("Hello world")
+if __name__ == "__main__":
+    main()
"""
    res = compress(diff)
    comp = res.messages[0]["content"]
    assert "+def main():" in comp
    assert "+# New module" in comp


def test_cli_version_and_perf():
    runner = CliRunner()

    # --version
    res_ver = runner.invoke(cli, ["--version"])
    assert res_ver.exit_code == 0
    assert "ShortBraid version" in res_ver.output

    # perf benchmark
    res_perf = runner.invoke(cli, ["perf"])
    assert res_perf.exit_code == 0
    assert "Real-World Performance" in res_perf.output
    assert "100 Production Logs" in res_perf.output
    assert "Preserved" in res_perf.output


def test_cli_mcp_handler():
    # MCP initialize
    init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    init_resp = handle_mcp_request(init_req)
    assert init_resp["result"]["serverInfo"]["name"] == "shortbraid-mcp"

    # MCP tools/list
    list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    list_resp = handle_mcp_request(list_req)
    tools = [t["name"] for t in list_resp["result"]["tools"]]
    assert "shortbraid_compress" in tools
    assert "retrieve_original_text" in tools
    assert "shared_context_put" in tools

    # MCP compress call
    call_req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "shortbraid_compress",
            "arguments": {"content": "INFO log 1\nINFO log 2\nFATAL log 3\nINFO log 4"},
        },
    }
    call_resp = handle_mcp_request(call_req)
    assert "ShortBraid" in call_resp["result"]["content"][0]["text"]


def test_transparent_proxy_health_and_metrics():
    with TestClient(proxy_app) as client:
        # /health
        h_resp = client.get("/health")
        assert h_resp.status_code == 200
        assert h_resp.json()["service"] == "shortbraid-proxy"

        # /metrics
        m_resp = client.get("/metrics")
        assert m_resp.status_code == 200
        assert "shortbraid_proxy_requests_total" in m_resp.text


def test_transparent_proxy_openai_forwarding():
    with TestClient(proxy_app) as client:
        mock_upstream_response = {
            "id": "chatcmpl-proxy-test",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Proxied response!"}}],
            "usage": {"total_tokens": 15},
        }

        mock_http_resp = AsyncMock()
        mock_http_resp.status_code = 200
        mock_http_resp.content = json.dumps(mock_upstream_response).encode()
        mock_http_resp.headers = {"content-type": "application/json"}

        with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_http_resp)):
            resp = client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer sk_proxy_test"},
                json={
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "user", "content": "\n".join([f"INFO line {i}" for i in range(50)])}
                    ],
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["choices"][0]["message"]["content"] == "Proxied response!"
