"""Unit tests for the SmartCrusher (no I/O, pure functions)."""

from app.workers.crusher import chunk_text, crush


def test_crush_strips_iso_timestamps():
    raw = '2024-01-15T10:30:00.123Z {"level":"info","msg":"hello"}'
    result = crush(raw)
    assert "2024-01-15T10:30:00.123Z" not in result.crushed
    assert "hello" in result.crushed


def test_crush_collapses_whitespace():
    raw = "line1\n\n\n\n\nline2"
    result = crush(raw)
    assert result.crushed == "line1\nline2"


def test_crush_dedupes_json_keys():
    raw = '{"a": 1, "a": 2, "b": 3}'
    result = crush(raw)
    # last-wins
    assert '"a":2' in result.crushed or '"a": 2' in result.crushed
    assert '"b":3' in result.crushed or '"b": 3' in result.crushed


def test_crush_strips_log_boilerplate():
    raw = '{"level":"info","msg":"hi"}'
    result = crush(raw)
    assert "level" not in result.crushed.lower()
    assert "hi" in result.crushed


def test_crush_empty():
    result = crush("")
    assert result.crushed == ""
    assert result.compression_ratio == 0.0


def test_crush_idempotent():
    raw = '{"a": 1} 2024-01-01T00:00:00Z'
    r1 = crush(raw)
    r2 = crush(r1.crushed)
    assert r1.crushed == r2.crushed


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
    raw = '{"a": 1, "a": 1, "a": 1, "level":"info"} 2024-01-01T00:00:00Z'
    result = crush(raw)
    assert result.compression_ratio < 1.0
    assert result.crushed_len < result.original_len
