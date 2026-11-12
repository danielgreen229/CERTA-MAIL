from __future__ import annotations

from pathlib import Path

from lead_assistant.tracing import MAX_STRING_CHARS, Tracer, read_trace, redact


def test_redact_masks_secrets_and_limits_length() -> None:
    assert "sk-ant-api03-abcdefgh12345678" not in redact("key sk-ant-api03-abcdefgh12345678 end")
    assert "abc.def.ghi-123456" not in redact("Authorization: Bearer abc.def.ghi-123456")
    assert "hunter2hunter2" not in redact('password="hunter2hunter2"')
    assert "s3cr3tvalue" not in redact("ANTHROPIC_API_KEY=s3cr3tvalue")
    assert redact("обычный текст") == "обычный текст"
    assert len(redact("x" * 5000)) == MAX_STRING_CHARS + 1


def test_tracer_writes_json_lines_and_cleans_nested_values(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "trace.jsonl"
    tracer = Tracer(path, run_id="r1", source="test")
    tracer.event("tool_call", tool="get_lead", lead_id=1, ok=True, duration_ms=1.5)
    tracer.event("error", message="token=abcdef123456", extra={"k": ["Bearer zzzzzzzzzzzz", 3]})
    events = read_trace(path)
    assert [event["event"] for event in events] == ["tool_call", "error"]
    assert events[0]["run_id"] == "r1" and events[0]["source"] == "test"
    assert events[0]["ts"].endswith("Z")
    raw = path.read_text("utf-8")
    assert "abcdef123456" not in raw and "zzzzzzzzzzzz" not in raw
    assert events[1]["extra"]["k"][1] == 3


def test_tracer_without_path_and_broken_lines(tmp_path: Path) -> None:
    assert Tracer(None).event("x", a=1)["a"] == 1
    path = tmp_path / "trace.jsonl"
    path.write_text('{"event": "ok"}\nnot json\n[1]\n', encoding="utf-8")
    assert read_trace(path) == [{"event": "ok"}]
    assert read_trace(tmp_path / "absent.jsonl") == []
