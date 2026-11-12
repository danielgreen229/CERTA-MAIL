"""Рабочий путь: агент на бесплатной модели через OpenAI-совместимый API.

Модель получает ровно те инструменты, которые объявил MCP-сервер проекта (три штуки), и
сама их вызывает. Этот модуль ведёт цикл «ответ модели → вызов инструмента через MCP →
результат модели» и возвращает наблюдаемые факты прогона.

Между чтением заявки и записью стоит разбор (decision.py): модель отвечает на вопросы о
заявке в структурированном виде, код проверяет цитаты и выводит категорию и приоритет.
Вызов update_lead с другими значениями до сервера не доходит.

По умолчанию API предоставляет локальный llama-server (см. llm.py), но подойдёт любая
система с тем же протоколом: Ollama, LM Studio, vLLM или бесплатный облачный сервис.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from lead_assistant.agent import (
    AgentOutcome,
    AgentRequest,
    ToolCall,
    ToolCallback,
    apply_tool_result,
    check_init,
    parse_tool_payload,
    summarize_arguments,
)
from lead_assistant.decision import ANALYSIS_SCHEMA, Decision, analysis_request, decide
from lead_assistant.llm import open_url
from lead_assistant.models import CATEGORIES, PRIORITIES, SERVER_NAME, TOOL_NAMES, LeadId
from lead_assistant.tracing import redact

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
MAX_NUDGES = 3
REPORT_REQUEST = (
    "Работа с инструментами завершена. Выдай итог по разделу «Итог» правил в формате JSON: "
    "поле summary — короткая сводка руководителю (не длиннее 12 строк), поле leads — по одной "
    "записи на каждую заявку, которую ты обрабатывал в этой сессии."
)

type Remember = Callable[[dict[str, Any]], None]


class LlmError(Exception):
    """Сбой обращения к модели. code попадает в трейс и определяет слой диагностики."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class McpCallError(Exception):
    """MCP-сервер перестал отвечать посреди сессии."""


def report_schema(ids: list[LeadId]) -> dict[str, Any]:
    """Схема итога: сервер модели гарантирует, что ответ ей соответствует."""
    text_or_null = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    lead = {
        "type": "object",
        "properties": {
            "id": {"enum": ids} if ids else {"type": "integer"},
            "category": {"enum": list(CATEGORIES)},
            "priority": {"enum": list(PRIORITIES)},
            "result": {"enum": ["written", "already_processed", "failed"]},
            "uncertain": {"type": "boolean"},
            "manager_check": text_or_null,
            "urgency_basis": text_or_null,
            "next_action": text_or_null,
        },
        "required": [
            "id", "category", "priority", "result",
            "uncertain", "manager_check", "urgency_basis", "next_action",
        ],
        "additionalProperties": False,
    }  # fmt: skip
    return {
        "type": "object",
        "properties": {"summary": {"type": "string"}, "leads": {"type": "array", "items": lead}},
        "required": ["summary", "leads"],
        "additionalProperties": False,
    }


def openai_tools(mcp_tools: list[Any]) -> list[dict[str, Any]]:
    """Переводит описания инструментов MCP в формат функций OpenAI-совместимого API."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.input_schema,
            },
        }
        for tool in mcp_tools
    ]


def write_instruction(lead_id: LeadId, decision: Decision) -> str:
    """Сообщает модели результат разбора: с какими значениями записывать заявку."""
    text = (
        f'Решение по заявке {lead_id!r}: category="{decision.category}", '
        f'priority="{decision.priority}". Вызови update_lead с этими значениями и '
        'status="processed". '
    )
    if decision.category == "spam":
        return text + "Для спама draft_reply должен быть null."
    return text + "Черновик составь по разделу «Черновик ответа» правил, на языке текста заявки."


class _Session:
    """Состояние одной сессии агента."""

    def __init__(self) -> None:
        self.listed: list[LeadId] = []  # заявки из первого ответа list_leads
        self.has_listing = False
        self.resolved: set[str] = set()  # запись подтверждена или заявку обработал кто-то другой
        self.touched: list[LeadId] = []  # заявки, по которым модель вызывала update_lead
        self.results: dict[str, str] = {}
        self.decisions: dict[str, Decision] = {}
        self.gate = True  # разбор перед записью; отключается, если сервер не умеет JSON-схемы
        self.nudges = 0
        self.mcp_failures = 0  # подряд идущие вызовы без ответа сервера


class LocalLlmBackend:
    """Агент на модели с OpenAI-совместимым API и инструментами MCP-сервера проекта."""

    def __init__(
        self,
        base_url: str,
        model: str,
        client: str,
        api_key: str | None = None,
        request_timeout: float = 600.0,
        max_tokens: int = 1500,
        temperature: float = 0.0,
        facts: dict[str, Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = client
        self.api_key = api_key
        self.request_timeout = request_timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.facts = facts or {}

    # --- обращение к модели -------------------------------------------------

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "User-Agent": "lead-assistant"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
        )
        try:
            with open_url(request, timeout=self.request_timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            if error.code in (401, 403):
                code = "AUTH_FAILED"
            elif "exceed_context_size" in detail or "context length" in detail.lower():
                code = "CONTEXT_FULL"
            else:
                code = f"LLM_HTTP_ERROR:{error.code}"
            raise LlmError(code, redact(detail)) from error
        except (urllib.error.URLError, OSError) as error:
            raise LlmError("LLM_UNAVAILABLE", redact(f"{self.base_url}: {error}")) from error
        try:
            data = json.loads(body)
            data["choices"][0]["message"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise LlmError(
                "LLM_BAD_RESPONSE", "ответ модели не похож на chat.completion"
            ) from error
        assert isinstance(data, dict)
        return data

    async def _chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        usage: dict[str, int],
        outcome: AgentOutcome,
        schema: tuple[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens if schema is None else 2 * self.max_tokens,
            "seed": 7,
        }
        if schema is None:
            payload["tools"] = tools
        else:
            name, body = schema
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": body},
            }
        data = await asyncio.to_thread(self._post, payload)
        reported = data.get("usage") or {}
        usage["requests"] += 1
        usage["input_tokens"] += int(reported.get("prompt_tokens") or 0)
        usage["output_tokens"] += int(reported.get("completion_tokens") or 0)
        model = data.get("model")
        if isinstance(model, str) and model and model not in outcome.models:
            outcome.models.append(model)
        message: dict[str, Any] = data["choices"][0]["message"]
        message["content"] = _THINK.sub("", str(message.get("content") or "")).strip()
        return message

    # --- сессия -------------------------------------------------------------

    async def run(self, request: AgentRequest, on_tool: ToolCallback) -> AgentOutcome:
        outcome = AgentOutcome()
        started = time.monotonic()
        usage = {"requests": 0, "input_tokens": 0, "output_tokens": 0}
        try:
            async with asyncio.timeout(request.timeout_seconds):
                await self._connect(request, on_tool, outcome, usage)
        except TimeoutError:
            outcome.error_code = "TIMEOUT"
            outcome.error_message = f"нет результата за {request.timeout_seconds:.0f} с"
        outcome.result = {
            "duration_ms": round((time.monotonic() - started) * 1000),
            "num_turns": usage["requests"],
            "usage": {
                "input_tokens": usage["input_tokens"] or None,
                "output_tokens": usage["output_tokens"] or None,
            },
            "billing": "local",
        }
        return outcome

    async def _connect(
        self,
        request: AgentRequest,
        on_tool: ToolCallback,
        outcome: AgentOutcome,
        usage: dict[str, int],
    ) -> None:
        from mcp import Client, StdioServerParameters

        params = StdioServerParameters(
            command=request.mcp_command, args=request.mcp_args, env=request.mcp_env
        )
        failure: LlmError | None = None
        try:
            async with Client(params) as mcp:
                listed = (await mcp.list_tools()).tools
                outcome.init = {
                    "model": self.facts.get("model") or self.model,
                    "client": self.client,
                    "tools": sorted(tool.name for tool in listed),
                    "mcp_servers": [{"name": SERVER_NAME, "status": "connected"}],
                    **{k: v for k, v in self.facts.items() if k != "model"},
                }
                problem = check_init(outcome.init)
                if problem is not None:
                    outcome.error_code, outcome.error_message = problem
                    return  # модель ещё не вызывалась
                try:
                    await self._loop(request, mcp, openai_tools(listed), on_tool, outcome, usage)
                except LlmError as error:
                    failure = error  # выходим из контекста MCP штатно, причину сообщаем ниже
                except McpCallError as error:
                    outcome.error_code = "MCP_UNAVAILABLE"
                    outcome.error_message = redact(str(error))
                except Exception as error:  # ошибка самого цикла, а не MCP и не модели
                    outcome.error_code = "BACKEND_ERROR"
                    outcome.error_message = redact(f"{type(error).__name__}: {error}")
        except Exception as error:  # сервер не стартовал или соединение оборвалось
            if outcome.error_code is None:
                outcome.error_code = "MCP_UNAVAILABLE"
                outcome.error_message = redact(f"{type(error).__name__}: {error}")
        if failure is not None:
            outcome.error_code = failure.code
            outcome.error_message = failure.message

    async def _loop(
        self,
        request: AgentRequest,
        mcp: Any,
        tools: list[dict[str, Any]],
        on_tool: ToolCallback,
        outcome: AgentOutcome,
        usage: dict[str, int],
    ) -> None:
        messages: list[dict[str, Any]] = []
        dialog = request.dialog_path.open("a", encoding="utf-8") if request.dialog_path else None

        def remember(message: dict[str, Any]) -> None:
            messages.append(message)
            if dialog is not None:
                dialog.write(json.dumps(message, ensure_ascii=False) + "\n")

        remember(
            {"role": "system", "content": request.system_prompt_path.read_text(encoding="utf-8")}
        )
        remember({"role": "user", "content": request.prompt})
        state = _Session()
        context_full = False
        try:
            try:
                await self._turns(
                    request, mcp, tools, on_tool, outcome, usage, state, messages, remember
                )
            except LlmError as error:
                if error.code != "CONTEXT_FULL":
                    if state.decisions:
                        self._report_from_decisions(outcome, state)
                    raise
                # Контекст модели исчерпан: сессия завершается, остальное заберёт следующая.
                context_full = True
                outcome.error_code = "CONTEXT_FULL"
                outcome.error_message = "контекст модели исчерпан; уменьшите --batch-size"
            if state.decisions:
                self._report_from_decisions(outcome, state)
            elif not context_full:
                await self._report(messages, tools, state.touched, outcome, usage, remember)
        finally:
            if dialog is not None:
                dialog.close()

    async def _turns(
        self,
        request: AgentRequest,
        mcp: Any,
        tools: list[dict[str, Any]],
        on_tool: ToolCallback,
        outcome: AgentOutcome,
        usage: dict[str, int],
        state: _Session,
        messages: list[dict[str, Any]],
        remember: Remember,
    ) -> None:
        """Шаги модели до завершения сессии."""
        for _turn in range(request.max_turns):
            reply = await self._chat(messages, tools, usage, outcome)
            calls = reply.get("tool_calls") or []
            text = str(reply.get("content") or "")
            remember({"role": "assistant", "content": text, "tool_calls": calls})
            if text:
                outcome.final_text = text

            if calls:
                read: list[tuple[LeadId, dict[str, Any]]] = []
                for call in calls:
                    result_text, record = await self._call_tool(mcp, call, outcome, state)
                    on_tool(record)
                    remember(
                        {"role": "tool", "tool_call_id": call.get("id"), "content": result_text}
                    )
                    self._track(record, result_text, state, read)
                for lead_id, lead in read:
                    await self._analyse(
                        lead_id, lead, request, messages, tools, usage, outcome, state, remember
                    )
                # Предел заявок на сессию держит раннер: контекст модели остаётся коротким,
                # остальные заявки заберёт следующая сессия.
                if request.batch_limit and len(state.resolved) >= request.batch_limit:
                    return
                continue

            # Модель остановилась. Проверяем по подтверждённым ответам, всё ли сделано.
            target = state.listed[: request.batch_limit] if request.batch_limit else state.listed
            pending = [i for i in target if repr(i) not in state.resolved]
            if state.nudges < MAX_NUDGES and (not state.has_listing or pending):
                state.nudges += 1
                reminder = (
                    f"Заявки {pending} всё ещё в статусе new. Продолжи: для каждой вызови "
                    "get_lead, затем update_lead."
                    if state.has_listing
                    else 'Начни с вызова list_leads со status="new".'
                )
                remember({"role": "user", "content": reminder})
                continue
            return
        outcome.error_code = "MAX_TURNS"
        outcome.error_message = f"превышен предел шагов модели: {request.max_turns}"

    @staticmethod
    def _track(
        record: ToolCall,
        result_text: str,
        state: _Session,
        read: list[tuple[LeadId, dict[str, Any]]],
    ) -> None:
        """Обновляет состояние сессии по подтверждённому ответу инструмента."""
        if record.tool == "list_leads" and record.ok and not state.has_listing:
            state.has_listing = True
            state.listed = [item["id"] for item in json.loads(result_text).get("leads", [])]
        first_read = record.lead_id is not None and repr(record.lead_id) not in state.decisions
        if record.tool == "get_lead" and record.ok and record.lead_id is not None and first_read:
            read.append((record.lead_id, json.loads(result_text)["lead"]))
        if record.tool == "update_lead" and record.lead_id is not None:
            key = repr(record.lead_id)
            if record.lead_id not in state.touched:
                state.touched.append(record.lead_id)
            if record.ok and record.result == "updated":
                state.results[key] = "written"
            elif record.ok or record.code == "CONFLICT":
                state.results[key] = "already_processed"
            else:
                state.results.setdefault(key, "failed")
            if record.ok or record.code == "CONFLICT":
                state.resolved.add(key)

    async def _analyse(
        self,
        lead_id: LeadId,
        lead: dict[str, Any],
        request: AgentRequest,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        usage: dict[str, int],
        outcome: AgentOutcome,
        state: _Session,
        remember: Remember,
    ) -> None:
        """Структурированный разбор прочитанной заявки и решение по нему."""
        if not state.gate:
            return
        question = {"role": "user", "content": analysis_request(lead_id, request.today)}
        try:
            reply = await self._chat(
                [*messages, question], tools, usage, outcome, ("lead_analysis", ANALYSIS_SCHEMA)
            )
            analysis = json.loads(str(reply.get("content") or ""))
        except LlmError as error:
            if not error.code.startswith("LLM_HTTP_ERROR:4"):
                raise
            state.gate = False  # сервис не поддерживает JSON-схемы: модель решает сама
            return
        except json.JSONDecodeError:
            return  # разбор не получен: запись этой заявки будет отклонена до повторного чтения
        if not isinstance(analysis, dict):
            return
        decision = decide(analysis, lead, request.today)
        state.decisions[repr(lead_id)] = decision
        # В истории остаётся короткая запись: полный текст вопросов занял бы контекст модели.
        remember({"role": "user", "content": f"Разбери заявку {lead_id!r} по пунктам правил."})
        compact = json.dumps(analysis, ensure_ascii=False, separators=(",", ":"))
        remember({"role": "assistant", "content": compact})
        remember({"role": "user", "content": write_instruction(lead_id, decision)})

    async def _call_tool(
        self, mcp: Any, call: dict[str, Any], outcome: AgentOutcome, state: _Session
    ) -> tuple[str, ToolCall]:
        """Выполняет вызов, запрошенный моделью, через MCP и возвращает текст для модели."""
        function = call.get("function") or {}
        name = str(function.get("name") or "")
        raw = function.get("arguments")
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            arguments = None
        lead_id, safe = summarize_arguments(name, arguments if isinstance(arguments, dict) else {})
        record = ToolCall(
            seq=len(outcome.tool_calls) + 1,
            tool_use_id=str(call.get("id") or ""),
            tool=name if name in TOOL_NAMES else "unknown",
            lead_id=lead_id,
            args=safe,
            started=time.monotonic(),
        )
        outcome.tool_calls.append(record)

        # Ошибки модели до сервера не доходят: это не сбой MCP.
        refusal: tuple[str, str] | None = None
        if name not in TOOL_NAMES:
            refusal = ("UNKNOWN_TOOL", f"unknown tool {name!r}; available: {list(TOOL_NAMES)}")
        elif not isinstance(arguments, dict):
            refusal = ("INVALID_TOOL_ARGUMENTS", "arguments must be a JSON object")
        elif name == "update_lead" and state.gate and lead_id is not None:
            decision = state.decisions.get(repr(lead_id))
            if decision is None:
                refusal = (
                    "READ_REQUIRED",
                    f"call get_lead for lead {lead_id!r} before update_lead",
                )
            elif (arguments.get("category"), arguments.get("priority")) != (
                decision.category,
                decision.priority,
            ):
                refusal = (
                    "ANALYSIS_MISMATCH",
                    f"use category={decision.category!r} and priority={decision.priority!r} "
                    f"for lead {lead_id!r}: they follow from the lead analysis",
                )
        if refusal is not None:
            record.ok = False
            record.code, message = refusal
            record.duration_ms = 0.0
            error = {"ok": False, "error": {"code": record.code, "message": message}}
            return json.dumps(error, ensure_ascii=False), record

        assert isinstance(arguments, dict)
        try:
            result = await mcp.call_tool(name, arguments)
        except Exception as error:
            # Вызов не вернул ответа: исход неизвестен. Модель по правилам сначала проверит
            # состояние заявки; если сервер не отвечает и дальше, сессия прекращается.
            state.mcp_failures += 1
            if state.mcp_failures >= 3:
                raise McpCallError(f"MCP-сервер не отвечает: {type(error).__name__}") from error
            record.code = "MCP_CALL_FAILED"
            lost = {"ok": False, "error": {"code": record.code, "message": "no response"}}
            return json.dumps(lost), record
        state.mcp_failures = 0
        content = [
            {"type": "text", "text": block.text}
            for block in result.content
            if hasattr(block, "text")
        ]
        apply_tool_result(record, content, result.is_error)
        payload = parse_tool_payload(content)
        if payload is not None:  # компактный JSON экономит контекст модели
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":")), record
        return "\n".join(block["text"] for block in content), record

    @staticmethod
    def _report_from_decisions(outcome: AgentOutcome, state: _Session) -> None:
        """Итог сессии по разборам заявок и подтверждённым исходам записи."""
        entries = [
            state.decisions[repr(lead_id)].report_entry(
                lead_id, state.results.get(repr(lead_id), "failed")
            )
            for lead_id in state.touched
            if repr(lead_id) in state.decisions
        ]
        block = json.dumps({"leads": entries}, ensure_ascii=False, indent=2)
        outcome.final_text = (
            f"Разобрано заявок в сессии: {len(entries)}. Категории и приоритеты выведены из "
            f"разбора каждой заявки.\n\n```json\n{block}\n```\n"
        )

    async def _report(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        ids: list[LeadId],
        outcome: AgentOutcome,
        usage: dict[str, int],
        remember: Remember,
    ) -> None:
        """Запрашивает итог в структурированном виде; при отказе оставляет текст модели."""
        remember({"role": "user", "content": REPORT_REQUEST})
        try:
            reply = await self._chat(
                messages, tools, usage, outcome, ("run_report", report_schema(ids))
            )
            text = str(reply.get("content") or "")
            data = json.loads(text)
        except (LlmError, json.JSONDecodeError):
            return  # итог останется тем, что модель написала сама; сверка это отметит
        remember({"role": "assistant", "content": text})
        leads = json.dumps({"leads": data.get("leads", [])}, ensure_ascii=False, indent=2)
        outcome.final_text = f"{data.get('summary', '')}\n\n```json\n{leads}\n```\n"
