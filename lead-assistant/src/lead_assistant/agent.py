"""Общие типы агента и необязательный бэкенд Claude Agent SDK.

Бэкенд ничего не знает о файле заявок и сводке: он проводит сессию, в которой модели
доступны только три MCP-инструмента, и возвращает наблюдаемые факты (вызовы инструментов,
их подтверждённые исходы, телеметрию рантайма, итоговый текст).

Рабочий путь проекта — локальная модель (local_backend.py). ClaudeSdkBackend оставлен как
вариант для тех, у кого есть авторизация Claude; он требует пакета claude-agent-sdk.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from lead_assistant.models import (
    CATEGORIES,
    PRIORITIES,
    SERVER_NAME,
    STATUS_PROCESSED,
    TOOL_NAMES,
    LeadId,
    is_valid_lead_id,
)
from lead_assistant.tracing import redact

TOOL_PREFIX = f"mcp__{SERVER_NAME}__"
EXPECTED_TOOLS: tuple[str, ...] = tuple(TOOL_PREFIX + name for name in TOOL_NAMES)
CLAUDE_DEFAULT_MODEL = "claude-opus-5-5"

# Значения аргументов, которые можно писать в трейс как есть. Всё остальное заменяется
# меткой: произвольная строка модели может содержать фрагмент текста заявки.
_SAFE_STATUSES = ("new", STATUS_PROCESSED)
_SAFE_UPDATE_VALUES: dict[str, tuple[str, ...]] = {
    "category": CATEGORIES,
    "priority": PRIORITIES,
    "status": (STATUS_PROCESSED,),
}


@dataclass
class ToolCall:
    """Один вызов инструмента моделью. Текстов заявок и черновиков здесь нет."""

    seq: int
    tool_use_id: str
    tool: str
    lead_id: LeadId | None
    args: dict[str, Any]
    started: float
    duration_ms: float | None = None
    ok: bool | None = None  # None — ответ инструмента не наблюдался
    code: str | None = None
    result: str | None = None
    count: int | None = None

    def to_trace(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "tool": self.tool,
            "lead_id": self.lead_id,
            "args": self.args,
            "ok": self.ok,
            "code": self.code,
            "result": self.result,
            "count": self.count,
            "duration_ms": self.duration_ms,
        }


@dataclass
class AgentRequest:
    system_prompt_path: Path
    prompt: str
    mcp_command: str
    mcp_args: list[str]
    mcp_env: dict[str, str]
    model: str
    max_turns: int
    timeout_seconds: float
    cwd: Path
    batch_limit: int | None = None  # предел заявок на сессию
    today: str = ""  # дата, от которой считается срочность
    dialog_path: Path | None = None


@dataclass
class AgentOutcome:
    init: dict[str, Any] | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    final_text: str = ""
    models: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    stderr_tail: list[str] = field(default_factory=list)


type ToolCallback = Callable[[ToolCall], None]


class AgentBackend(Protocol):
    """Рантайм модели. Реальная реализация — ClaudeSdkBackend; в тестах — сценарий."""

    async def run(self, request: AgentRequest, on_tool: ToolCallback) -> AgentOutcome: ...


def parse_tool_payload(content: object) -> dict[str, Any] | None:
    """Достаёт JSON-тело из ответа инструмента (SDK добавляет к ошибке текстовый префикс)."""
    if isinstance(content, list):
        text = "\n".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    elif isinstance(content, str):
        text = content
    else:
        return None
    start = text.find("{")
    if start < 0:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def summarize_arguments(
    tool: str, arguments: dict[str, Any]
) -> tuple[LeadId | None, dict[str, Any]]:
    """Оставляет от аргументов вызова только безопасные для трейса поля."""
    raw_id = arguments.get("id")
    lead_id: LeadId | None = raw_id if is_valid_lead_id(raw_id) else None
    safe: dict[str, Any] = {}
    if tool == "list_leads":
        status = arguments.get("status")
        safe["status"] = status if status is None or status in _SAFE_STATUSES else "other"
    elif tool == "update_lead":
        for key, allowed in _SAFE_UPDATE_VALUES.items():
            value = arguments.get(key)
            safe[key] = value if isinstance(value, str) and value in allowed else "invalid"
        draft = arguments.get("draft_reply")
        safe["draft_chars"] = len(draft) if isinstance(draft, str) else None
        safe["draft_is_null"] = draft is None
    return lead_id, safe


def apply_tool_result(call: ToolCall, content: object, is_error: bool | None) -> None:
    """Записывает в вызов подтверждённый исход по ответу инструмента."""
    call.duration_ms = round((time.monotonic() - call.started) * 1000, 1)
    payload = parse_tool_payload(content)
    if is_error or (payload is not None and payload.get("ok") is False):
        call.ok = False
        error = payload.get("error") if payload else None
        code = error.get("code") if isinstance(error, dict) else None
        # Ошибка без машинного кода — отказ на уровне MCP: схема аргументов или сбой сервера.
        call.code = code if isinstance(code, str) else "MCP_TOOL_ERROR"
        return
    if payload is None or payload.get("ok") is not True:
        call.ok = None
        call.code = "UNPARSEABLE_RESULT"
        return
    call.ok = True
    result = payload.get("result")
    call.result = result if isinstance(result, str) else None
    count = payload.get("count")
    call.count = count if isinstance(count, int) else None


class ClaudeSdkBackend:
    """Рабочий путь: Claude Agent SDK (управляет встроенным Claude Code CLI)."""

    async def run(self, request: AgentRequest, on_tool: ToolCallback) -> AgentOutcome:
        outcome = AgentOutcome()
        try:
            async with asyncio.timeout(request.timeout_seconds):
                await self._run(request, on_tool, outcome)
        except TimeoutError:
            outcome.error_code = "TIMEOUT"
            outcome.error_message = f"no result within {request.timeout_seconds:.0f}s"
        return outcome

    async def _run(
        self, request: AgentRequest, on_tool: ToolCallback, outcome: AgentOutcome
    ) -> None:
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError:
            outcome.error_code = "BACKEND_NOT_INSTALLED"
            outcome.error_message = (
                "пакет claude-agent-sdk не установлен: pip install 'lead-assistant[claude]'"
            )
            return
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ClaudeSDKError,
            CLINotFoundError,
            ResultMessage,
            SystemMessage,
            TextBlock,
            ToolResultBlock,
            ToolUseBlock,
            UserMessage,
            query,
        )

        def keep_stderr(line: str) -> None:
            outcome.stderr_tail.append(redact(line.rstrip()))
            del outcome.stderr_tail[:-8]

        options = ClaudeAgentOptions(
            system_prompt={"type": "file", "path": str(request.system_prompt_path)},
            tools=[],  # встроенные инструменты Claude Code отключены
            mcp_servers={
                SERVER_NAME: {
                    "type": "stdio",
                    "command": request.mcp_command,
                    "args": request.mcp_args,
                    "env": request.mcp_env,
                }
            },
            strict_mcp_config=True,  # никакие другие MCP-серверы не подключаются
            allowed_tools=list(EXPECTED_TOOLS),
            setting_sources=[],  # пользовательские и проектные настройки не читаются
            permission_mode="default",
            model=request.model,
            max_turns=request.max_turns,
            cwd=request.cwd,
            extra_args={"no-session-persistence": None},  # тексты заявок не копятся в ~/.claude
            stderr=keep_stderr,
        )

        pending: dict[str, ToolCall] = {}
        api_error_seen = False
        stream = query(prompt=request.prompt, options=options)
        dialog = request.dialog_path.open("a", encoding="utf-8") if request.dialog_path else None
        try:
            async for message in stream:
                if dialog is not None:
                    record = {"type": type(message).__name__, **dataclasses.asdict(message)}
                    dialog.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                if isinstance(message, SystemMessage):
                    if message.subtype == "init":
                        outcome.init = _init_facts(message.data)
                        problem = check_init(outcome.init)
                        if problem is not None:
                            outcome.error_code, outcome.error_message = problem
                            return  # модель ещё не вызывалась: останавливаемся
                elif isinstance(message, AssistantMessage):
                    if message.model not in outcome.models:
                        outcome.models.append(message.model)
                    if message.error is not None:
                        api_error_seen = True
                    if message.error is not None and outcome.error_code is None:
                        outcome.error_code = (
                            "AUTH_FAILED"
                            if message.error == "authentication_failed"
                            else f"MODEL_API_ERROR:{message.error}"
                        )
                    texts = [b.text for b in message.content if isinstance(b, TextBlock)]
                    if texts:
                        outcome.final_text = "\n".join(texts)
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            tool = block.name.removeprefix(TOOL_PREFIX)
                            lead_id, safe = summarize_arguments(tool, block.input)
                            call = ToolCall(
                                seq=len(outcome.tool_calls) + 1,
                                tool_use_id=block.id,
                                tool=tool,
                                lead_id=lead_id,
                                args=safe,
                                started=time.monotonic(),
                            )
                            outcome.tool_calls.append(call)
                            pending[block.id] = call
                elif isinstance(message, UserMessage):
                    if isinstance(message.content, list):
                        for block in message.content:
                            if isinstance(block, ToolResultBlock):
                                finished = pending.pop(block.tool_use_id, None)
                                if finished is not None:
                                    apply_tool_result(finished, block.content, block.is_error)
                                    on_tool(finished)
                elif isinstance(message, ResultMessage):
                    outcome.result = _result_facts(message)
                    if message.is_error and outcome.error_code is None:
                        outcome.error_code = (
                            "MAX_TURNS"
                            if message.subtype == "error_max_turns"
                            else f"RUNTIME_ERROR:{message.subtype}"
                        )
                    if outcome.error_code and not outcome.error_message:
                        # result содержит служебный текст только при ошибке API;
                        # в остальных случаях это ответ модели, и в журнал он не идёт.
                        detail = message.result if api_error_seen else None
                        outcome.error_message = redact(
                            str(detail or message.errors or message.subtype)
                        )
        except CLINotFoundError as exc:
            outcome.error_code = "CLI_NOT_FOUND"
            outcome.error_message = redact(str(exc))
        except ClaudeSDKError as exc:
            # После ошибки авторизации CLI завершается с ненулевым кодом: причина уже известна.
            if outcome.error_code is None:
                outcome.error_code = "RUNTIME_PROCESS_ERROR"
                outcome.error_message = redact(str(exc))
        finally:
            # Явно закрываем поток: при досрочном выходе процесс CLI должен завершиться.
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
            if dialog is not None:
                dialog.close()


def check_init(init: dict[str, Any]) -> tuple[str, str] | None:
    """Проверяет границы до первого обращения к модели: сервер подключён, инструментов три."""
    servers = {s.get("name"): s.get("status") for s in init.get("mcp_servers", [])}
    if servers.get(SERVER_NAME) != "connected":
        return (
            "MCP_UNAVAILABLE",
            f"MCP server {SERVER_NAME!r} is not connected: status={servers.get(SERVER_NAME)!r}",
        )
    tools = sorted(init.get("tools", []))
    # Claude Code добавляет к именам префикс mcp__leads__; локальный рантайм — нет.
    if sorted(name.removeprefix(TOOL_PREFIX) for name in tools) != sorted(TOOL_NAMES):
        return ("TOOLS_MISMATCH", f"model tools differ from the three project tools: {tools}")
    return None


def _init_facts(data: dict[str, Any]) -> dict[str, Any]:
    servers = data.get("mcp_servers") or []
    return {
        "model": data.get("model"),
        "client": f"Claude Code {data.get('claude_code_version')}",
        "tools": list(data.get("tools") or []),
        "mcp_servers": [
            {"name": s.get("name"), "status": s.get("status")}
            for s in servers
            if isinstance(s, dict)
        ],
        "permission_mode": data.get("permissionMode"),
        "api_key_source": data.get("apiKeySource"),
    }


def _result_facts(message: Any) -> dict[str, Any]:
    usage = message.usage or {}
    return {
        "subtype": message.subtype,
        "is_error": message.is_error,
        "api_error_status": message.api_error_status,
        "duration_ms": message.duration_ms,
        "duration_api_ms": message.duration_api_ms,
        "num_turns": message.num_turns,
        "total_cost_usd": message.total_cost_usd,
        "usage": {
            key: usage.get(key)
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            )
        },
        "model_usage": json.loads(json.dumps(message.model_usage or {}, default=str)),
        "permission_denials": len(message.permission_denials or []),
    }


def mcp_server_command() -> tuple[str, list[str]]:
    """Команда запуска MCP-сервера тем же интерпретатором, без оболочки и относительных путей."""
    return sys.executable, ["-m", "lead_assistant.server"]
