"""Прогон целиком: сценарная модель + настоящий MCP-сервер через stdio + независимая сверка."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from lead_assistant.agent import AgentOutcome, AgentRequest, ToolCallback
from lead_assistant.diagnose import diagnose
from lead_assistant.rules import load_rules, operator_prompt
from lead_assistant.runner import RunConfig, exit_code, run_processing
from lead_assistant.storage import Lead, LeadStore, parse_leads, serialize_leads, sha256_hex
from lead_assistant.tracing import read_trace
from tests.helpers import ORIGINAL, Decision, ScriptedBackend, simple_decision

pytestmark = pytest.mark.anyio


def config(leads_file: Path, **overrides: Any) -> RunConfig:
    return RunConfig(
        leads_file=leads_file,
        runs_dir=leads_file.parent / "runs dir",
        today="2026-11-11",
        **overrides,
    )


async def run(leads_file: Path, backend: Any, **overrides: Any) -> dict[str, Any]:
    return await run_processing(config(leads_file, **overrides), backend, echo=lambda _line: None)


def sha(path: Path) -> str:
    return sha256_hex(path.read_bytes())


async def test_regular_run_processes_every_new_lead(leads_file: Path) -> None:
    result = await run(leads_file, ScriptedBackend())
    rec = result["reconciliation"]

    assert result["status"] == "ok" and exit_code(result["status"]) == 0
    assert rec["counts"] == {"found": 14, "written": 14, "already_processed": 0, "failed": 0}
    assert rec["counts_consistent"] and rec["found_ids"] == list(range(1, 15))
    assert rec["remaining_new_ids"] == [] and rec["integrity_violations"] == []
    assert rec["report_mismatches"] == [] and rec["warnings"] == []
    assert result["runtime"]["only_project_tools"] is True

    after = parse_leads(leads_file.read_bytes())
    original = parse_leads(ORIGINAL.read_bytes())
    assert after[14] == original[14]  # ранее обработанная заявка 15 не изменилась
    assert [lead["id"] for lead in after] == [lead["id"] for lead in original]
    # Счётчики сводки совпадают с тем, что реально лежит в файле.
    assert rec["by_category"] == {"question": 12, "spam": 2}
    assert sum(1 for lead in after if lead.get("category") == "spam") == 2
    assert rec["file_status_counts"] == {"processed": 15}

    run_dir = Path(result["run_dir"])
    assert json.loads((run_dir / "run.json").read_text("utf-8"))["run_id"] == result["run_id"]
    summary = (run_dir / "summary.md").read_text("utf-8")
    assert "Найдено новых: 14" in summary and "Записано: 14" in summary
    assert "ID 3" in summary  # спорный случай передан менеджеру


async def test_repeat_run_finds_nothing_and_keeps_checksum(leads_file: Path) -> None:
    await run(leads_file, ScriptedBackend())
    checksum = sha(leads_file)
    repeat = await run(leads_file, ScriptedBackend())
    assert repeat["status"] == "ok"
    assert repeat["reconciliation"]["counts"] == {
        "found": 0, "written": 0, "already_processed": 0, "failed": 0,
    }  # fmt: skip
    assert repeat["metrics"]["tool_calls"]["by_tool"] == {"list_leads": 1}
    assert repeat["leads_file"]["changed"] is False and sha(leads_file) == checksum


async def test_trace_has_metrics_but_no_lead_text_or_drafts(leads_file: Path) -> None:
    result = await run(leads_file, ScriptedBackend())
    run_dir = Path(result["run_dir"])
    runner_events = read_trace(run_dir / "trace.jsonl")
    server_events = read_trace(run_dir / "mcp_trace.jsonl")

    names = [event["event"] for event in runner_events]
    assert names[0] == "run_start" and names[-1] == "run_end"
    assert names.count("tool_call") == 29  # 1 list + 14 get + 14 update
    assert len(server_events) == 29
    assert all(event["run_id"] == result["run_id"] for event in runner_events + server_events)
    assert result["metrics"]["tool_calls"]["by_tool"] == {
        "list_leads": 1, "get_lead": 14, "update_lead": 14,
    }  # fmt: skip
    assert result["metrics"]["duration_ms"] > 0
    assert result["metrics"]["cost"]["status"] == "unavailable"  # сценарий не сообщает стоимость

    technical = "".join(
        (run_dir / name).read_text("utf-8")
        for name in ("trace.jsonl", "mcp_trace.jsonl", "run.json")
    )
    for lead in parse_leads(ORIGINAL.read_bytes()):
        assert str(lead["text"]) not in technical
        if lead["contact"]:
            assert str(lead["contact"]) not in technical
    assert "Получили обращение" not in technical  # текст черновика


async def test_skipped_lead_is_reported_not_hidden(leads_file: Path) -> None:
    def skip_seven(lead: Lead) -> Decision | None:
        return None if lead["id"] == 7 else simple_decision(lead)

    result = await run(leads_file, ScriptedBackend(decide=skip_seven))
    rec = result["reconciliation"]
    assert result["status"] == "incomplete" and exit_code(result["status"]) == 1
    assert rec["counts"] == {"found": 14, "written": 13, "already_processed": 0, "failed": 1}
    assert rec["failed"] == [{"id": 7, "reason": "NO_UPDATE_ATTEMPT"}]
    assert rec["remaining_new_ids"] == [7]
    assert "MISSING_IN_MODEL_REPORT: 7" in rec["report_mismatches"]
    assert diagnose(Path(result["run_dir"]))["layers"] == ["model"]


async def test_false_confirmation_by_model_is_caught(leads_file: Path) -> None:
    def skip_seven(lead: Lead) -> Decision | None:
        return None if lead["id"] == 7 else simple_decision(lead)

    def claim_seven_written(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        fake = {"id": 7, "category": "sale", "priority": "high", "result": "written"}
        return [*entries, fake]

    backend = ScriptedBackend(decide=skip_seven, report_patch=claim_seven_written)
    result = await run(leads_file, backend)
    rec = result["reconciliation"]
    # Слова модели не засчитываются: файл говорит, что заявка 7 осталась new.
    assert rec["counts"]["written"] == 13 and rec["failed"][0]["id"] == 7
    assert any(m.startswith("RESULT_MISMATCH: 7") for m in rec["report_mismatches"])
    assert result["status"] == "incomplete"
    assert LeadStore(leads_file).get_lead(7)["status"] == "new"


async def test_model_report_that_differs_from_file_is_flagged(leads_file: Path) -> None:
    def lie_about_priority(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        entries[0]["priority"] = "high"
        return entries

    result = await run(leads_file, ScriptedBackend(report_patch=lie_about_priority))
    rec = result["reconciliation"]
    assert rec["report_mismatches"] == ["PRIORITY_MISMATCH: 1 model='high' file='medium'"]
    assert rec["leads"][0]["priority"] == "medium"  # в сводку идёт значение из файла
    assert result["status"] == "ok_with_warnings"


async def test_lead_processed_by_someone_else_during_run_is_counted_once(leads_file: Path) -> None:
    def competitor(lead: Lead) -> None:
        if lead["id"] == 5:
            LeadStore(leads_file).update_lead(5, "sale", "high", "processed", "Ответ коллеги")

    result = await run(leads_file, ScriptedBackend(before_update=competitor))
    rec = result["reconciliation"]
    assert rec["counts"] == {"found": 14, "written": 13, "already_processed": 1, "failed": 0}
    assert rec["already_processed_ids"] == [5] and rec["counts_consistent"]
    assert result["metrics"]["tool_calls"]["errors_by_code"] == {"CONFLICT": 1}
    assert LeadStore(leads_file).get_lead(5)["draft_reply"] == "Ответ коллеги"  # не перезаписано
    assert result["status"] == "ok"


async def test_lost_tool_response_is_resolved_by_file_state(leads_file: Path) -> None:
    result = await run(leads_file, ScriptedBackend(lose_result_for=frozenset({2})))
    rec = result["reconciliation"]
    entry = next(e for e in rec["leads"] if e["id"] == 2)
    assert entry["result"] == "written" and entry["evidence"] == "state_confirmed"
    assert rec["counts"]["written"] == 14 and rec["counts"]["failed"] == 0
    assert result["metrics"]["tool_calls"]["without_result"] == 1


async def test_corrupt_file_stops_before_model(leads_file: Path) -> None:
    leads_file.write_bytes(leads_file.read_bytes()[:-30])
    checksum = sha(leads_file)
    backend = ScriptedBackend()
    result = await run(leads_file, backend)
    assert result["status"] == "failed" and exit_code(result["status"]) == 2
    assert result["error"]["code"] == "STORAGE_CORRUPT" and result["error"]["layer"] == "storage"
    assert backend.requests == []  # модель не вызывалась
    assert sha(leads_file) == checksum


class AuthFailingBackend:
    async def run(self, request: AgentRequest, on_tool: ToolCallback) -> AgentOutcome:
        return AgentOutcome(
            models=["<synthetic>"],
            error_code="AUTH_FAILED",
            error_message="Not logged in · Please run /login",
            result={"duration_ms": 50, "num_turns": 1, "total_cost_usd": 0, "usage": {}},
        )


async def test_authorization_failure_is_not_blamed_on_model(leads_file: Path) -> None:
    checksum = sha(leads_file)
    result = await run(leads_file, AuthFailingBackend())
    assert result["status"] == "failed" and exit_code(result["status"]) == 2
    assert result["error"]["layer"] == "authorization"
    assert result["runtime"]["model"] is None  # «<synthetic>» моделью не считается
    assert result["reconciliation"]["counts"]["failed"] == 14
    assert sha(leads_file) == checksum
    assert diagnose(Path(result["run_dir"]))["layers"] == ["authorization"]


async def test_skip_model_if_empty(tmp_path: Path) -> None:
    leads_file = tmp_path / "leads.json"
    shutil.copyfile(ORIGINAL, leads_file)
    await run(leads_file, ScriptedBackend())
    backend = ScriptedBackend()
    result = await run(leads_file, backend, skip_model_if_empty=True)
    assert backend.requests == [] and result["status"] == "ok"
    assert result["reconciliation"]["counts"]["found"] == 0


async def test_runner_passes_only_safe_configuration_to_backend(leads_file: Path) -> None:
    backend = ScriptedBackend()
    result = await run(leads_file, backend, model="claude-opus-5-5")
    request = backend.requests[0]
    assert request.prompt == operator_prompt("2026-11-11", 5) and request.batch_limit == 5
    assert request.prompt.startswith("Обработай новые заявки. Текущая дата: 2026-11-11.")
    assert request.system_prompt_path.name == "rules.md"
    assert request.mcp_env["LEADS_FILE"] == str(leads_file)
    assert request.mcp_env["LEADS_RUN_ID"] == result["run_id"]
    assert result["runtime"]["model_requested"] == "claude-opus-5-5"
    assert result["rules"]["version"] == load_rules().version


async def test_new_lead_appended_during_run_is_picked_up_by_next_session(leads_file: Path) -> None:
    def crm_appends(lead: Lead) -> None:
        if lead["id"] == 14:
            leads = parse_leads(leads_file.read_bytes())
            leads.append({"id": 16, "text": "Новая заявка из CRM", "status": "new"})
            style = LeadStore(leads_file).snapshot().style
            leads_file.write_bytes(serialize_leads(leads, style))

    result = await run(leads_file, ScriptedBackend(before_update=crm_appends))
    rec = result["reconciliation"]
    # Появление заявки во время прогона — не нарушение целостности; её забирает следующая сессия.
    assert rec["integrity_violations"] == [] and rec["arrived_during_run_ids"] == [16]
    assert rec["counts"] == {"found": 15, "written": 15, "already_processed": 0, "failed": 0}
    assert rec["remaining_new_ids"] == [] and result["metrics"]["sessions"] == 2
    assert "NEW_LEADS_ARRIVED_DURING_RUN: [16]" in rec["warnings"]
    assert result["status"] == "ok_with_warnings" and exit_code(result["status"]) == 0
