"""Оркестрация прогона: снимок файла, сессии агента, независимая сверка, артефакты.

Прогон состоит из одной или нескольких сессий агента. В каждой сессии модель сама
вызывает list_leads, get_lead и update_lead и обрабатывает не более batch_size заявок;
следующая сессия начинается с чистого контекста и забирает оставшиеся. Так контекст
модели остаётся коротким, а заявка, не доведённая в одной сессии, не теряется.

Артефакты прогона в runs/<run_id>/:
* run.json        — структурированный итог (учёт по ID, метрики, рантайм, пояснения модели);
* summary.md      — сводка руководителю;
* trace.jsonl     — технический трейс раннера (без текстов заявок и черновиков);
* mcp_trace.jsonl — трейс MCP-сервера (то же ограничение);
* model_report.md — итоговые сообщения модели по сессиям;
* llm_server.log  — журнал локального сервера модели;
* dialog.jsonl    — полный диалог с моделью, только при --save-dialog.
"""

from __future__ import annotations

import json
import math
import secrets
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from lead_assistant.agent import (
    TOOL_PREFIX,
    AgentBackend,
    AgentOutcome,
    AgentRequest,
    ToolCall,
    mcp_server_command,
)
from lead_assistant.models import (
    ENV_LEADS_FILE,
    ENV_LOG_LEVEL,
    ENV_RUN_ID,
    ENV_TRACE_FILE,
    STATUS_NEW,
    TOOL_NAMES,
    ErrorCode,
    LeadError,
)
from lead_assistant.reconcile import merge_reports, reconcile, run_status
from lead_assistant.report import render_summary
from lead_assistant.rules import load_rules, operator_prompt
from lead_assistant.storage import LeadStore, Snapshot
from lead_assistant.tracing import Tracer, utc_now

CLOUD_COST_NOTE = (
    "Стоимость сообщает клиент модели. При авторизации по подписке это расчётный "
    "эквивалент по тарифам API, а не фактическое списание."
)
LOCAL_COST_NOTE = (
    "Локальная модель: платы за токены нет. Затраты прогона — время и электроэнергия "
    "сервера; оценка в деньгах не вычисляется."
)
# Ошибки сессии, после которых следующая сессия не имеет смысла.
_FATAL_PREFIXES = ("AUTH_", "MCP_", "TOOLS_", "LLM_", "CLI_", "RUNTIME_", "MODEL_API_", "BACKEND_")


@dataclass
class RunConfig:
    leads_file: Path
    runs_dir: Path
    model: str = ""  # запрошенная модель: для записи в run.json
    today: str = field(default_factory=lambda: date.today().isoformat())
    batch_size: int = 5  # предел заявок на одну сессию агента
    max_turns: int = 150
    timeout_seconds: float = 1800.0
    save_dialog: bool = False
    skip_model_if_empty: bool = False
    # Команда запуска MCP-сервера; по умолчанию — сервер проекта тем же интерпретатором.
    mcp_command: tuple[str, list[str]] | None = None


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


def error_layer(code: str) -> str:
    """Слой, в котором возник сбой: по нему выбирается способ диагностики."""
    if code == "AUTH_FAILED":
        return "authorization"
    if code in ("MCP_UNAVAILABLE", "TOOLS_MISMATCH", "MCP_TOOL_ERROR", "UNPARSEABLE_RESULT"):
        return "mcp"
    if code in (
        ErrorCode.INVALID_ARGUMENT,
        ErrorCode.NOT_FOUND,
        ErrorCode.CONFLICT,
        ErrorCode.DRAFT_POLICY,
    ):
        return "validation"
    if code.startswith("STORAGE_") or code in (ErrorCode.DUPLICATE_ID, ErrorCode.LOCK_TIMEOUT):
        return "storage"
    model_codes = (
        "NO_UPDATE_ATTEMPT", "NOT_READ", "MAX_TURNS", "UNKNOWN_TOOL", "INVALID_TOOL_ARGUMENTS",
        "READ_REQUIRED", "ANALYSIS_MISMATCH",
    )  # fmt: skip
    if code in model_codes or code.startswith("REPORT_"):
        return "model"
    return "runtime"  # сервер модели, клиент, тайм-аут


def tool_metrics(calls: list[ToolCall]) -> dict[str, Any]:
    by_tool = Counter(call.tool for call in calls)
    errors = Counter(call.code for call in calls if call.ok is False and call.code)
    durations: dict[str, list[float]] = {}
    for call in calls:
        if call.duration_ms is not None:
            durations.setdefault(call.tool, []).append(call.duration_ms)
    return {
        "total": len(calls),
        "by_tool": dict(by_tool),
        "errors_by_code": dict(errors),
        "without_result": sum(1 for call in calls if call.ok is None),
        "avg_duration_ms": {
            tool: round(sum(values) / len(values), 1) for tool, values in durations.items()
        },
    }


def usage_metrics(result: dict[str, Any] | None) -> dict[str, Any]:
    """Разделяет сообщённые рантаймом значения, оценку и отсутствие данных."""
    if not result:
        return {
            "tokens": None,
            "tokens_status": "unavailable",
            "cost": {"reported_usd": None, "estimated_usd": None, "status": "unavailable"},
        }
    tokens = result.get("usage") or {}
    has_tokens = any(value is not None for value in tokens.values())
    reported = result.get("total_cost_usd")
    if result.get("billing") == "local":
        cost = {
            "reported_usd": None,
            "estimated_usd": None,
            "status": "not_applicable",
            "note": LOCAL_COST_NOTE,
        }
    else:
        cost = {
            "reported_usd": reported,
            "estimated_usd": None,  # собственная оценка не вычисляется
            "status": "reported" if reported is not None else "unavailable",
            "note": CLOUD_COST_NOTE,
        }
    return {
        "tokens": tokens if has_tokens else None,
        "tokens_status": "reported" if has_tokens else "unavailable",
        "tokens_by_model": result.get("model_usage") or None,
        "cost": cost,
    }


def combine_results(sessions: list[AgentOutcome]) -> dict[str, Any] | None:
    """Складывает телеметрию сессий в итог прогона."""
    results = [session.result for session in sessions if session.result]
    if not results:
        return None

    def total(key: str) -> Any:
        values = [r[key] for r in results if r.get(key) is not None]
        return sum(values) if values else None

    token_keys = {key for r in results for key in (r.get("usage") or {})}
    usage: dict[str, Any] = {}
    for key in sorted(token_keys):
        values = [r["usage"][key] for r in results if (r.get("usage") or {}).get(key) is not None]
        usage[key] = sum(values) if values else None
    combined: dict[str, Any] = {
        "duration_ms": total("duration_ms"),
        "duration_api_ms": total("duration_api_ms"),
        "num_turns": total("num_turns"),
        "total_cost_usd": total("total_cost_usd"),
        "usage": usage,
        "billing": results[0].get("billing"),
    }
    model_usage = [r["model_usage"] for r in results if r.get("model_usage")]
    if model_usage:
        combined["model_usage"] = model_usage[-1] if len(model_usage) == 1 else model_usage
    return combined


def _is_fatal(code: str | None) -> bool:
    return bool(code) and str(code).startswith(_FATAL_PREFIXES)


async def run_processing(
    config: RunConfig, backend: AgentBackend, echo: Callable[[str], None] = print
) -> dict[str, Any]:
    """Выполняет один прогон и возвращает структурированный итог (он же run.json)."""
    run_id = new_run_id()
    run_dir = config.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    tracer = Tracer(run_dir / "trace.jsonl", run_id=run_id, source="runner")
    rules = load_rules()
    store = LeadStore(config.leads_file)
    started_at = utc_now()
    started = time.monotonic()

    run: dict[str, Any] = {
        "run_id": run_id,
        "started_at": started_at,
        "today": config.today,
        "leads_file": {"path": str(config.leads_file)},
        "rules": {"version": rules.version, "sha256": rules.sha256},
        "runtime": {"backend": type(backend).__name__, "model_requested": config.model or None},
        "error": None,
    }
    echo(f"[прогон {run_id}] файл заявок: {config.leads_file}")

    before: Snapshot | None = None
    try:
        before = store.snapshot()
    except LeadError as error:
        run["error"] = {"code": error.code.value, "message": error.message, "layer": "storage"}
        tracer.event("error", stage="snapshot_before", code=error.code.value)

    sessions: list[AgentOutcome] = []
    calls: list[ToolCall] = []
    model_invoked = False
    after: Snapshot | None = before
    if before is not None:
        new_count = sum(1 for lead in before.leads if lead["status"] == STATUS_NEW)
        run["leads_file"]["sha256_before"] = before.sha256
        tracer.event(
            "run_start",
            leads_file=str(config.leads_file),
            sha256_before=before.sha256,
            total=len(before.leads),
            new=new_count,
            rules_version=rules.version,
            model_requested=config.model,
            batch_size=config.batch_size,
            today=config.today,
        )
        echo(f"[файл] заявок: {len(before.leads)}, новых: {new_count}, sha256: {before.sha256}")

        if new_count == 0 and config.skip_model_if_empty:
            tracer.event("model_skipped", reason="no_new_leads")
            echo("[модель] новых заявок нет — модель не вызывается (--skip-model-if-empty)")
        else:
            model_invoked = True
            command, args = config.mcp_command or mcp_server_command()
            session_limit = math.ceil(new_count / max(config.batch_size, 1)) + 2
            for number in range(1, session_limit + 1):
                if number > 1:
                    try:
                        still_new = sum(
                            1 for lead in store.snapshot().leads if lead["status"] == STATUS_NEW
                        )
                    except LeadError:
                        break  # файл перестал читаться: причину зафиксирует снимок «после»
                    if still_new == 0:
                        break
                    echo(f"[сессия {number}] осталось новых заявок: {still_new}")
                offset = len(calls)

                def on_tool(call: ToolCall, offset: int = offset, number: int = number) -> None:
                    call.seq += offset
                    tracer.event("tool_call", session=number, **call.to_trace())
                    target = f" id={call.lead_id!r}" if call.lead_id is not None else ""
                    detail = call.result or (
                        f"{call.count} шт." if call.count is not None else "ok"
                    )
                    verdict = detail if call.ok else f"ОШИБКА {call.code}"
                    echo(f"  [{call.seq}] {call.tool}{target} → {verdict} ({call.duration_ms} мс)")

                request = AgentRequest(
                    system_prompt_path=rules.path,
                    prompt=operator_prompt(config.today, config.batch_size),
                    mcp_command=command,
                    mcp_args=args,
                    mcp_env={
                        ENV_LEADS_FILE: str(config.leads_file),
                        ENV_TRACE_FILE: str(run_dir / "mcp_trace.jsonl"),
                        ENV_RUN_ID: run_id,
                        ENV_LOG_LEVEL: "WARNING",  # журнал сервера не засоряет вывод прогона
                        "PYTHONIOENCODING": "utf-8",
                    },
                    model=config.model,
                    max_turns=config.max_turns,
                    timeout_seconds=config.timeout_seconds,
                    cwd=run_dir,
                    batch_limit=config.batch_size,
                    today=config.today,
                    dialog_path=run_dir / "dialog.jsonl" if config.save_dialog else None,
                )
                outcome = await backend.run(request, on_tool)
                sessions.append(outcome)
                for call in outcome.tool_calls:
                    if call.ok is None and call.duration_ms is None:  # ответа не было
                        call.seq += offset
                        tracer.event("tool_call", session=number, **call.to_trace())
                calls.extend(outcome.tool_calls)
                if outcome.init:
                    tracer.event("runtime_init", session=number, **outcome.init)
                    if number == 1:
                        echo(
                            f"[рантайм] {outcome.init.get('client')} · модель "
                            f"{outcome.init.get('model')} · инструменты модели: "
                            f"{', '.join(outcome.init.get('tools', [])) or 'нет'}"
                        )
                if outcome.result:
                    tracer.event("agent_result", session=number, **outcome.result)
                if outcome.error_code:
                    layer = error_layer(outcome.error_code)
                    tracer.event(
                        "error",
                        stage="agent",
                        session=number,
                        code=outcome.error_code,
                        layer=layer,
                        message=outcome.error_message,
                        stderr_tail=outcome.stderr_tail,
                    )
                    if run["error"] is None:
                        run["error"] = {
                            "code": outcome.error_code,
                            "message": outcome.error_message,
                            "layer": layer,
                        }
                progressed = any(c.tool == "update_lead" and c.ok for c in outcome.tool_calls)
                if _is_fatal(outcome.error_code) or not progressed:
                    break
            (run_dir / "model_report.md").write_text(
                "\n\n".join(
                    f"<!-- сессия {index} -->\n{session.final_text}"
                    for index, session in enumerate(sessions, start=1)
                ),
                encoding="utf-8",
            )

        try:
            after = store.snapshot()
        except LeadError as error:
            # Файл перестал читаться во время прогона: сверяем с исходным состоянием.
            run["error"] = {"code": error.code.value, "message": error.message, "layer": "storage"}
            tracer.event("error", stage="snapshot_after", code=error.code.value)
            after = None

    before_leads = before.leads if before else []
    after_leads = after.leads if after else before_leads
    final_text = merge_reports([session.final_text for session in sessions])
    reconciliation = reconcile(before_leads, after_leads, calls, final_text, model_invoked)
    if before is not None and after is None:
        reconciliation["integrity_violations"].append("FILE_UNREADABLE_AFTER_RUN")

    inits = [session.init for session in sessions if session.init]
    first = inits[0] if inits else {}
    models = [m for session in sessions for m in session.models if m and m != "<synthetic>"]
    run["runtime"].update(
        {key: value for key, value in first.items() if key not in ("tools", "mcp_servers")}
    )
    run["runtime"].update(
        {
            "models_seen": sorted(set(models)),
            "tools": first.get("tools"),
            "mcp_servers": first.get("mcp_servers"),
            "only_project_tools": all(
                sorted(t.removeprefix(TOOL_PREFIX) for t in init.get("tools") or [])
                == sorted(TOOL_NAMES)
                for init in inits
            )
            if inits
            else None,
        }
    )
    if not run["runtime"].get("model"):
        run["runtime"]["model"] = models[0] if models else None
    if after is not None:
        run["leads_file"]["sha256_after"] = after.sha256
        run["leads_file"]["changed"] = before is not None and before.sha256 != after.sha256
    combined = combine_results(sessions)
    run["reconciliation"] = reconciliation
    run["metrics"] = {
        "duration_ms": round((time.monotonic() - started) * 1000),
        "runtime_duration_ms": (combined or {}).get("duration_ms"),
        "api_duration_ms": (combined or {}).get("duration_api_ms"),
        "num_turns": (combined or {}).get("num_turns"),
        "sessions": len(sessions),
        "model_invoked": model_invoked,
        "tool_calls": tool_metrics(calls),
        **usage_metrics(combined),
    }
    run["status"] = run_status(reconciliation, run["error"]["code"] if run["error"] else None)
    if before is None:
        run["status"] = "failed"
    run["finished_at"] = utc_now()

    (run_dir / "run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "summary.md").write_text(render_summary(run), encoding="utf-8")
    tracer.event(
        "run_end",
        status=run["status"],
        counts=reconciliation["counts"],
        failed=[{"id": f["id"], "reason": f["reason"]} for f in reconciliation["failed"]],
        integrity_violations=len(reconciliation["integrity_violations"]),
        report_mismatches=len(reconciliation["report_mismatches"]),
        sessions=len(sessions),
        duration_ms=run["metrics"]["duration_ms"],
        sha256_after=run["leads_file"].get("sha256_after"),
    )
    run["run_dir"] = str(run_dir)
    return run


def exit_code(status: str) -> int:
    """0 — все найденные заявки учтены как обработанные; 1 — не полностью; 2 — не выполнен."""
    return {"ok": 0, "ok_with_warnings": 0, "incomplete": 1}.get(status, 2)
