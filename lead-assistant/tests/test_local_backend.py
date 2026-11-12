"""Рабочий путь целиком: цикл агента на OpenAI-совместимом API + настоящий MCP-сервер."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any, ClassVar

import pytest

from lead_assistant.diagnose import diagnose
from lead_assistant.local_backend import LocalLlmBackend, openai_tools, report_schema
from lead_assistant.runner import RunConfig, exit_code, run_processing
from lead_assistant.storage import LeadStore, parse_leads, sha256_hex
from tests.fake_llm import BAD_DRAFT, GOOD_DRAFT, Behaviour, FakeLlm
from tests.helpers import ORIGINAL

pytestmark = pytest.mark.anyio


def backend(url: str, **extra: Any) -> LocalLlmBackend:
    return LocalLlmBackend(url, model="fake-model", client="fake llm", request_timeout=30, **extra)


async def run(leads_file: Path, llm: LocalLlmBackend, **overrides: Any) -> dict[str, Any]:
    config = RunConfig(
        leads_file=leads_file, runs_dir=leads_file.parent / "runs", today="2026-11-11", **overrides
    )
    return await run_processing(config, llm, echo=lambda _line: None)


async def test_model_gets_exactly_three_project_tools_and_processes_everything(
    leads_file: Path,
) -> None:
    with FakeLlm() as fake:
        result = await run(leads_file, backend(fake.url), save_dialog=True)
    rec = result["reconciliation"]

    assert result["status"] == "ok" and exit_code(result["status"]) == 0
    assert rec["counts"] == {"found": 14, "written": 14, "already_processed": 0, "failed": 0}
    assert result["metrics"]["sessions"] == 3  # по пять заявок на сессию: 5 + 5 + 4
    assert result["metrics"]["tool_calls"]["by_tool"] == {
        "list_leads": 3, "get_lead": 14, "update_lead": 14,
    }  # fmt: skip
    assert result["runtime"]["only_project_tools"] is True
    assert result["runtime"]["tools"] == ["get_lead", "list_leads", "update_lead"]
    assert result["runtime"]["client"] == "fake llm" and result["runtime"]["model"] == "fake-model"

    # Модели объявлены только три инструмента, и это видно в каждом запросе к ней.
    for payload in fake.behaviour.requests:
        if "tools" in payload:
            names = sorted(tool["function"]["name"] for tool in payload["tools"])
            assert names == ["get_lead", "list_leads", "update_lead"]
    system = fake.behaviour.requests[0]["messages"][0]
    assert system["role"] == "system" and "Правила обработки заявок" in system["content"]
    assert "не более 5 заявок" in fake.behaviour.requests[0]["messages"][1]["content"]

    # Телеметрия: токены сообщены, стоимость для локальной модели не применяется.
    assert result["metrics"]["tokens"]["input_tokens"] > 0
    assert result["metrics"]["cost"]["status"] == "not_applicable"
    assert result["metrics"]["cost"]["reported_usd"] is None

    original = parse_leads(ORIGINAL.read_bytes())
    after = parse_leads(leads_file.read_bytes())
    assert after[14] == original[14] and after[0]["draft_reply"] == GOOD_DRAFT
    dialog = (Path(result["run_dir"]) / "dialog.jsonl").read_text("utf-8")
    assert '"role": "tool"' in dialog and "Ольга Смирнова" in dialog  # диалог — по явному флагу


async def test_repeat_run_and_repeats_by_contact(leads_file: Path) -> None:
    with FakeLlm() as fake:
        first = await run(leads_file, backend(fake.url))
        checksum = sha256_hex(leads_file.read_bytes())
        second = await run(leads_file, backend(fake.url))
    assert second["reconciliation"]["counts"]["found"] == 0 and second["status"] == "ok"
    assert second["leads_file"]["changed"] is False
    assert sha256_hex(leads_file.read_bytes()) == checksum

    # Повтор обращения (заявки 1 и 11, один контакт) находит код, а не модель.
    entries = {e["id"]: e for e in first["reconciliation"]["leads"]}
    assert entries[11]["repeat_of"] == [1] and entries[1]["repeat_of"] == [11]
    assert entries[11]["uncertain"] is True and "заявке 1" in entries[11]["manager_check"]
    assert "repeat_of" not in entries[2]


async def test_model_that_stops_early_is_reminded(leads_file: Path) -> None:
    with FakeLlm(Behaviour(stop_after=3)) as fake:
        result = await run(leads_file, backend(fake.url))
    assert result["reconciliation"]["counts"]["written"] == 14 and result["status"] == "ok"
    reminders = [
        m["content"]
        for payload in fake.behaviour.requests
        for m in payload["messages"]
        if m["role"] == "user" and "всё ещё в статусе new" in m["content"]
    ]
    assert reminders and "[4, 5]" in reminders[0]


async def test_forgotten_lead_is_retried_then_reported(leads_file: Path) -> None:
    with FakeLlm(Behaviour(skip_ids=(7,))) as fake:
        result = await run(leads_file, backend(fake.url))
    rec = result["reconciliation"]
    assert rec["counts"]["written"] == 13 and rec["remaining_new_ids"] == [7]
    assert rec["failed"] == [{"id": 7, "reason": "NOT_READ"}]
    assert result["status"] == "incomplete" and exit_code(result["status"]) == 1
    assert result["metrics"]["sessions"] >= 2  # следующая сессия пробовала ещё раз
    assert diagnose(Path(result["run_dir"]))["layers"] == ["model"]


async def test_unsupported_draft_is_rejected_by_server_and_rewritten(leads_file: Path) -> None:
    with FakeLlm(Behaviour(bad_draft_ids=(5,))) as fake:
        result = await run(leads_file, backend(fake.url))
    assert result["metrics"]["tool_calls"]["errors_by_code"] == {"DRAFT_POLICY": 1}
    assert result["reconciliation"]["counts"]["written"] == 14
    stored = LeadStore(leads_file).get_lead(5)["draft_reply"]
    assert stored == GOOD_DRAFT and stored != BAD_DRAFT  # выдуманные факты в файл не попали
    assert result["status"] == "ok"


async def test_model_mistakes_do_not_reach_the_server(leads_file: Path) -> None:
    behaviour = Behaviour(unknown_tool_once=True, broken_arguments_once=True)
    with FakeLlm(behaviour) as fake:
        result = await run(leads_file, backend(fake.url))
    errors = result["metrics"]["tool_calls"]["errors_by_code"]
    assert errors == {"UNKNOWN_TOOL": 1, "INVALID_TOOL_ARGUMENTS": 1}
    assert result["reconciliation"]["counts"]["written"] == 14  # модель исправилась
    server_trace = (Path(result["run_dir"]) / "mcp_trace.jsonl").read_text("utf-8")
    assert "delete_lead" not in server_trace  # несуществующий инструмент до MCP не дошёл


async def test_report_falls_back_to_text_when_schema_is_unsupported(leads_file: Path) -> None:
    with FakeLlm(Behaviour(reject_schema=True)) as fake:
        result = await run(leads_file, backend(fake.url))
    rec = result["reconciliation"]
    assert rec["counts"]["written"] == 14  # счётчики не зависят от отчёта модели
    assert "REPORT_MISSING" in rec["warnings"] and result["status"] == "ok_with_warnings"


@pytest.mark.parametrize(
    ("status", "code", "layer"),
    [(500, "LLM_HTTP_ERROR:500", "runtime"), (401, "AUTH_FAILED", "authorization")],
)
async def test_model_service_errors_are_classified(
    leads_file: Path, status: int, code: str, layer: str
) -> None:
    checksum = sha256_hex(leads_file.read_bytes())
    with FakeLlm(Behaviour(http_status=status)) as fake:
        result = await run(leads_file, backend(fake.url, api_key="secret-key-value"))
    assert result["status"] == "failed" and exit_code(result["status"]) == 2
    assert result["error"]["code"] == code and result["error"]["layer"] == layer
    assert result["metrics"]["sessions"] == 1  # после такой ошибки новые сессии не начинаются
    assert sha256_hex(leads_file.read_bytes()) == checksum
    assert diagnose(Path(result["run_dir"]))["layers"] == [layer]
    technical = "".join(p.read_text("utf-8") for p in Path(result["run_dir"]).glob("*.json*"))
    assert "secret-key-value" not in technical


async def test_unreachable_model_server(leads_file: Path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    result = await run(leads_file, backend(f"http://127.0.0.1:{port}/v1"))
    assert result["error"]["code"] == "LLM_UNAVAILABLE" and result["error"]["layer"] == "runtime"
    assert result["reconciliation"]["counts"]["failed"] == 14


async def test_mcp_failure_is_detected_before_the_model_is_called(leads_file: Path) -> None:
    with FakeLlm() as fake:
        result = await run(
            leads_file,
            backend(fake.url),
            mcp_command=("python-that-does-not-exist", ["-m", "lead_assistant.server"]),
        )
    assert result["error"]["code"] == "MCP_UNAVAILABLE" and result["error"]["layer"] == "mcp"
    assert fake.behaviour.requests == []  # к модели не обращались


def test_report_schema_and_tool_conversion() -> None:
    schema = report_schema([1, "A-2"])
    lead = schema["properties"]["leads"]["items"]
    assert lead["properties"]["id"] == {"enum": [1, "A-2"]}
    assert lead["properties"]["priority"]["enum"] == ["high", "medium", "low"]
    assert set(lead["required"]) == set(lead["properties"])
    assert report_schema([])["properties"]["leads"]["items"]["properties"]["id"] == {
        "type": "integer"
    }

    class Tool:
        name = "get_lead"
        description = "Return the lead"
        input_schema: ClassVar[dict[str, Any]] = {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
        }

    converted = openai_tools([Tool()])
    assert converted == [
        {
            "type": "function",
            "function": {
                "name": "get_lead",
                "description": "Return the lead",
                "parameters": Tool.input_schema,
            },
        }
    ]
    assert json.dumps(converted)  # сериализуется в запрос


async def test_priority_follows_the_analysis_not_the_model(leads_file: Path) -> None:
    # Разбор находит последствие у заявки 9; попытка записать другой приоритет не проходит.
    behaviour = Behaviour(urgent_ids=(9,), wrong_priority_once=True)
    with FakeLlm(behaviour) as fake:
        result = await run(leads_file, backend(fake.url))
    assert result["metrics"]["tool_calls"]["errors_by_code"] == {"ANALYSIS_MISMATCH": 1}
    assert result["reconciliation"]["counts"]["written"] == 14 and result["status"] == "ok"
    entries = {e["id"]: e for e in result["reconciliation"]["leads"]}
    assert entries[9]["priority"] == "high" and "ошибочное списание" in entries[9]["urgency_basis"]
    assert entries[1]["priority"] == "medium" and entries[1]["urgency_basis"] is None
    assert LeadStore(leads_file).get_lead(9)["priority"] == "high"
    server_trace = (Path(result["run_dir"]) / "mcp_trace.jsonl").read_text("utf-8")
    assert server_trace.count('"tool": "update_lead"') == 14  # отклонённый вызов до MCP не дошёл
