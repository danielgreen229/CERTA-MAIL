"""Общие средства тестов: сценарная «модель» и запуск независимых процессов."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

from lead_assistant.agent import (
    EXPECTED_TOOLS,
    AgentOutcome,
    AgentRequest,
    ToolCall,
    ToolCallback,
    apply_tool_result,
    parse_tool_payload,
    summarize_arguments,
)
from lead_assistant.draft_policy import detect_language
from lead_assistant.models import LeadId
from lead_assistant.storage import Lead

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = PROJECT_ROOT / "data" / "leads.original.json"
WORKER = Path(__file__).with_name("worker.py")


@dataclass
class Decision:
    category: str
    priority: str
    draft_reply: str | None


def simple_decision(lead: Lead) -> Decision:
    """Детерминированное решение сценарной модели: достаточно для проверки механики."""
    text = str(lead["text"])
    if "!!!" in text or "t.me/" in text:
        return Decision("spam", "low", None)
    if detect_language(text) == "en":  # черновик пишется на языке заявки
        return Decision("question", "medium", f"Hello! We received your request {lead['id']}.")
    return Decision("question", "medium", f"Здравствуйте! Получили обращение {lead['id']}.")


class ScriptedBackend:
    """Заменяет модель сценарием, но ходит в настоящий MCP-сервер через stdio."""

    def __init__(
        self,
        decide: Callable[[Lead], Decision | None] = simple_decision,
        before_update: Callable[[Lead], None] | None = None,
        lose_result_for: frozenset[LeadId] = frozenset(),
        report_patch: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
        tools: tuple[str, ...] = EXPECTED_TOOLS,
    ) -> None:
        self.decide = decide
        self.before_update = before_update
        self.lose_result_for = lose_result_for
        self.report_patch = report_patch
        self.tools = tools
        self.requests: list[AgentRequest] = []

    async def run(self, request: AgentRequest, on_tool: ToolCallback) -> AgentOutcome:
        self.requests.append(request)
        outcome = AgentOutcome(
            init={
                "model": "scripted-model",
                "client": "scripted test backend",
                "tools": list(self.tools),
                "mcp_servers": [{"name": "leads", "status": "connected"}],
            },
            models=["scripted-model"],
        )
        params = StdioServerParameters(
            command=request.mcp_command, args=request.mcp_args, env=request.mcp_env
        )
        entries: list[dict[str, Any]] = []
        async with Client(params) as client:

            async def call(tool: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
                lead_id, safe = summarize_arguments(tool, arguments)
                record = ToolCall(
                    seq=len(outcome.tool_calls) + 1,
                    tool_use_id=f"scripted-{len(outcome.tool_calls) + 1}",
                    tool=tool,
                    lead_id=lead_id,
                    args=safe,
                    started=time.monotonic(),
                )
                outcome.tool_calls.append(record)
                result = await client.call_tool(tool, arguments)
                content = [
                    {"type": "text", "text": block.text}
                    for block in result.content
                    if hasattr(block, "text")
                ]
                if tool == "update_lead" and lead_id in self.lose_result_for:
                    return None  # ответ «потерян»: исход вызова неизвестен
                apply_tool_result(record, content, result.is_error)
                on_tool(record)
                return parse_tool_payload(content)

            listing = await call("list_leads", {"status": "new"})
            assert listing is not None
            for item in listing["leads"]:
                fetched = await call("get_lead", {"id": item["id"]})
                assert fetched is not None
                lead = fetched["lead"]
                decision = self.decide(lead)
                if decision is None:
                    continue
                if self.before_update is not None:
                    self.before_update(lead)
                payload = await call(
                    "update_lead",
                    {
                        "id": lead["id"],
                        "category": decision.category,
                        "priority": decision.priority,
                        "status": "processed",
                        "draft_reply": decision.draft_reply,
                    },
                )
                if payload is None or payload.get("ok"):
                    result_name = "written"
                    if payload is not None and payload.get("result") == "unchanged":
                        result_name = "already_processed"
                elif payload["error"]["code"] == "CONFLICT":
                    result_name = "already_processed"
                else:
                    result_name = "failed"
                entries.append(
                    {
                        "id": lead["id"],
                        "category": decision.category,
                        "priority": decision.priority,
                        "result": result_name,
                        "uncertain": decision.category == "spam",
                        "manager_check": "проверить отправителя"
                        if decision.category == "spam"
                        else None,
                        "urgency_basis": "основание" if decision.priority == "high" else None,
                        "next_action": "действие" if decision.priority == "high" else None,
                    }
                )
        if self.report_patch is not None:
            entries = self.report_patch(entries)
        report = json.dumps({"leads": entries}, ensure_ascii=False)
        outcome.final_text = f"Сводка сценария.\n\n```json\n{report}\n```"
        outcome.result = {"duration_ms": 1, "duration_api_ms": 0, "num_turns": 1, "usage": {}}
        return outcome


def start_worker(leads_file: Path, *args: str) -> subprocess.Popen[str]:
    """Запускает независимый процесс-писатель (отдельный интерпретатор)."""
    return subprocess.Popen(
        [sys.executable, str(WORKER), str(leads_file), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


def finish_worker(process: subprocess.Popen[str]) -> tuple[int, dict[str, Any]]:
    stdout, stderr = process.communicate(timeout=120)
    lines = [line for line in stdout.splitlines() if line.strip()]
    payload: dict[str, Any] = json.loads(lines[-1]) if lines else {"stderr": stderr[-500:]}
    return process.returncode, payload
