"""Unit tests for the Crusher adapter and chunking engine."""

from shortbraid.server.workers.crusher import chunk_text, crush


def test_crush_compresses_log_data():
    raw = "\n".join([f"2024-01-15 10:30:{i:02d} INFO Worker heartbeat ping {i}" for i in range(50)])
    result = crush(raw)
    assert result.compression_ratio < 0.5
    assert result.crushed_len < result.original_len


def test_crush_collapses_repeated_filler():
    raw = "Here is the summary:\n\n\n\n\nAs mentioned above, the task succeeded."
    result = crush(raw)
    assert len(result.crushed) <= len(raw)
    assert "task succeeded" in result.crushed


def test_crush_dedupes_json_array_records():
    raw = '[{"id": 1, "status": "ok"}, {"id": 2, "status": "ok"}, {"id": 3, "status": "ok"}]'
    result = crush(raw)
    assert "status" in result.crushed
    assert result.crushed_len > 0


def test_crush_preserves_anomalies_and_errors():
    raw = (
        "2024-01-15 INFO Normal operation\n"
        "2024-01-15 INFO Normal operation\n"
        "2024-01-15 FATAL Database connection pool exhausted\n"
        "2024-01-15 INFO Normal operation"
    )
    result = crush(raw)
    assert "Database connection pool exhausted" in result.crushed


def test_crush_empty():
    result = crush("")
    assert result.crushed == ""
    assert result.compression_ratio == 0.0


def test_crush_idempotent():
    raw = "INFO Starting server at port 8000\nINFO Ready to accept connections"
    r1 = crush(raw)
    r2 = crush(r1.crushed)
    assert len(r2.crushed) <= len(r1.crushed)


def test_chunk_text_short():
    text = "hello world"
    chunks = chunk_text(text, max_chars=100)
    assert chunks == ["hello world"]


def test_chunk_text_long():
    text = "x" * 1000
    chunks = chunk_text(text, max_chars=400, overlap=100)
    assert len(chunks) >= 3
    assert all(len(c) <= 400 for c in chunks)


def test_compression_ratio_lower_is_better():
    raw = "\n".join([f"INFO line {i}: ok" for i in range(100)])
    result = crush(raw)
    assert result.compression_ratio < 1.0
    assert result.crushed_len < result.original_len


def test_chunk_text_overlap_content():
    text = "0123456789" * 10  # 100 chars
    chunks = chunk_text(text, max_chars=40, overlap=10)
    assert len(chunks) >= 3
    assert chunks[0][-10:] == chunks[1][:10]
