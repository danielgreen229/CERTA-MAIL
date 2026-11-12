from __future__ import annotations

import time

from lead_assistant.agent import (
    EXPECTED_TOOLS,
    ToolCall,
    apply_tool_result,
    check_init,
    parse_tool_payload,
    summarize_arguments,
)
from lead_assistant.runner import error_layer, tool_metrics, usage_metrics


def new_call(tool: str = "update_lead") -> ToolCall:
    return ToolCall(1, "id", tool, 1, {}, time.monotonic())


def test_parse_tool_payload_handles_sdk_error_prefix() -> None:
    text = 'Error executing tool update_lead: {"ok": false, "error": {"code": "CONFLICT"}}'
    assert parse_tool_payload(text) == {"ok": False, "error": {"code": "CONFLICT"}}
    assert parse_tool_payload([{"type": "text", "text": '{"ok": true, "count": 3}'}]) == {
        "ok": True,
        "count": 3,
    }
    assert parse_tool_payload("2 validation errors for get_leadArguments") is None
    assert parse_tool_payload(None) is None
    assert parse_tool_payload("{broken") is None


def test_apply_tool_result_outcomes() -> None:
    updated = new_call()
    apply_tool_result(updated, '{"ok": true, "result": "updated", "id": 1}', False)
    assert (updated.ok, updated.result, updated.code) == (True, "updated", None)

    conflict = new_call()
    apply_tool_result(conflict, 'Error: {"ok": false, "error": {"code": "CONFLICT"}}', True)
    assert (conflict.ok, conflict.code) == (False, "CONFLICT")

    schema = new_call("get_lead")
    apply_tool_result(schema, "1 validation error for get_leadArguments", True)
    assert (schema.ok, schema.code) == (False, "MCP_TOOL_ERROR")

    garbage = new_call()
    apply_tool_result(garbage, "ok", False)
    assert (garbage.ok, garbage.code) == (None, "UNPARSEABLE_RESULT")

    listing = new_call("list_leads")
    apply_tool_result(listing, '{"ok": true, "count": 14, "leads": []}', None)
    assert listing.count == 14 and listing.duration_ms is not None


def test_summarize_arguments_drops_texts() -> None:
    draft = "Уважаемый Игорь, приносим извинения."
    lead_id, safe = summarize_arguments(
        "update_lead",
        {
            "id": 2,
            "category": "complaint",
            "priority": "high",
            "status": "processed",
            "draft_reply": draft,
        },
    )
    assert lead_id == 2
    assert safe == {
        "category": "complaint", "priority": "high", "status": "processed",
        "draft_chars": len(draft), "draft_is_null": False,
    }  # fmt: skip
    assert draft not in str(safe)

    # Длинное «значение категории» (например, вставленный текст заявки) в трейс не попадает.
    _, injected = summarize_arguments("update_lead", {"id": 1, "category": "x" * 500})
    assert injected["category"] == "invalid"
    assert summarize_arguments("list_leads", {"status": "текст заявки"})[1] == {"status": "other"}
    assert summarize_arguments("get_lead", {"id": True}) == (None, {})
    assert summarize_arguments("list_leads", {"status": "new"}) == (None, {"status": "new"})


def test_check_init_enforces_three_project_tools() -> None:
    connected = [{"name": "leads", "status": "connected"}]
    assert check_init({"tools": list(EXPECTED_TOOLS), "mcp_servers": connected}) is None
    # Локальный рантайм объявляет инструменты без префикса Claude Code.
    bare = ["get_lead", "list_leads", "update_lead"]
    assert check_init({"tools": bare, "mcp_servers": connected}) is None

    extra = check_init({"tools": [*EXPECTED_TOOLS, "Bash"], "mcp_servers": connected})
    assert extra is not None and extra[0] == "TOOLS_MISMATCH"
    missing = check_init({"tools": list(EXPECTED_TOOLS[:2]), "mcp_servers": connected})
    assert missing is not None and missing[0] == "TOOLS_MISMATCH"
    failed = check_init({"tools": [], "mcp_servers": [{"name": "leads", "status": "failed"}]})
    assert failed is not None and failed[0] == "MCP_UNAVAILABLE"
    assert check_init({"tools": [], "mcp_servers": []}) is not None


def test_error_layers() -> None:
    assert error_layer("AUTH_FAILED") == "authorization"
    assert error_layer("MCP_UNAVAILABLE") == "mcp" and error_layer("TOOLS_MISMATCH") == "mcp"
    assert error_layer("INVALID_ARGUMENT") == "validation"
    assert error_layer("DRAFT_POLICY") == "validation"
    assert error_layer("UNKNOWN_TOOL") == "model" and error_layer("LLM_UNAVAILABLE") == "runtime"
    for code in ("STORAGE_CORRUPT", "STORAGE_IO", "DUPLICATE_ID", "LOCK_TIMEOUT"):
        assert error_layer(code) == "storage"
    assert error_layer("NO_UPDATE_ATTEMPT") == "model" and error_layer("MAX_TURNS") == "model"
    assert error_layer("TIMEOUT") == "runtime" and error_layer("CLI_NOT_FOUND") == "runtime"


def test_usage_metrics_separate_reported_from_unavailable() -> None:
    assert usage_metrics(None)["cost"] == {
        "reported_usd": None, "estimated_usd": None, "status": "unavailable",
    }  # fmt: skip
    reported = usage_metrics(
        {"usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0.12}
    )
    assert reported["tokens_status"] == "reported" and reported["cost"]["status"] == "reported"
    assert reported["cost"]["reported_usd"] == 0.12 and reported["cost"]["estimated_usd"] is None
    empty = usage_metrics({"usage": {}, "total_cost_usd": None})
    assert empty["tokens_status"] == "unavailable" and empty["cost"]["status"] == "unavailable"


def test_tool_metrics() -> None:
    first, second = new_call("get_lead"), new_call("update_lead")
    apply_tool_result(first, '{"ok": true}', False)
    apply_tool_result(second, '{"ok": false, "error": {"code": "CONFLICT"}}', True)
    metrics = tool_metrics([first, second, new_call("update_lead")])
    assert metrics["total"] == 3 and metrics["by_tool"] == {"get_lead": 1, "update_lead": 2}
    assert metrics["errors_by_code"] == {"CONFLICT": 1} and metrics["without_result"] == 1
