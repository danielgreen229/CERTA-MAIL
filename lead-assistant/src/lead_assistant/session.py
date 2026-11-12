"""Сверка сессии, проведённой вне раннера (например, /process-leads в Claude Code).

    python -m lead_assistant.session begin              # снимок «до», печатает переменные окружения
    ...сессия обработки с LEADS_TRACE_FILE и LEADS_RUN_ID из вывода begin...
    python -m lead_assistant.session end RUN_DIR [--report итог_модели.md]

Команда end строит те же run.json и summary.md, что и раннер: счётчики берутся из
состояния файла и трейса MCP-сервера, а не из слов модели. Телеметрии модели (токены,
стоимость) у такой сессии нет — это отмечается в run.json.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

from lead_assistant.agent import ToolCall
from lead_assistant.backends import use_utf8_console
from lead_assistant.cli import DEFAULT_LEADS_FILE
from lead_assistant.models import ENV_LEADS_FILE, ENV_RUN_ID, ENV_TRACE_FILE, LeadError
from lead_assistant.reconcile import reconcile, run_status
from lead_assistant.report import render_summary
from lead_assistant.rules import load_rules
from lead_assistant.runner import exit_code, new_run_id, tool_metrics, usage_metrics
from lead_assistant.storage import LeadStore, parse_leads, sha256_hex
from lead_assistant.tracing import read_trace, utc_now

BEFORE_COPY = "before.json"
SESSION_META = "session.json"


def begin(leads_file: Path, runs_dir: Path, today: str) -> dict[str, Any]:
    """Сохраняет состояние файла до сессии. Копия удаляется командой end."""
    LeadStore(leads_file).snapshot()  # файл должен быть корректным до начала работы
    run_id = new_run_id()
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    shutil.copyfile(leads_file, run_dir / BEFORE_COPY)
    meta = {
        "run_id": run_id,
        "started_at": utc_now(),
        "today": today,
        "leads_file": str(leads_file),
        "run_dir": str(run_dir),
        "env": {
            ENV_LEADS_FILE: str(leads_file),
            ENV_TRACE_FILE: str(run_dir / "mcp_trace.jsonl"),
            ENV_RUN_ID: run_id,
        },
    }
    (run_dir / SESSION_META).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return meta


def calls_from_trace(events: list[dict[str, Any]]) -> list[ToolCall]:
    """Восстанавливает вызовы инструментов по трейсу сервера."""
    calls: list[ToolCall] = []
    for event in events:
        if event.get("event") != "tool_call":
            continue
        calls.append(
            ToolCall(
                seq=len(calls) + 1,
                tool_use_id=f"trace-{len(calls) + 1}",
                tool=str(event.get("tool")),
                lead_id=event.get("lead_id"),
                args={"category": event.get("category"), "priority": event.get("priority")},
                started=0.0,
                duration_ms=event.get("duration_ms"),
                ok=event.get("ok"),
                code=event.get("code"),
                result=event.get("result"),
                count=event.get("count"),
            )
        )
    return calls


def end(
    run_dir: Path, report_text: str, model: str | None, keep_before: bool = False
) -> dict[str, Any]:
    meta = json.loads((run_dir / SESSION_META).read_text(encoding="utf-8"))
    leads_file = Path(meta["leads_file"])
    before_raw = (run_dir / BEFORE_COPY).read_bytes()
    before = parse_leads(before_raw)
    after_snapshot = LeadStore(leads_file).snapshot()
    calls = calls_from_trace(read_trace(run_dir / "mcp_trace.jsonl"))
    rules = load_rules()

    reconciliation = reconcile(before, after_snapshot.leads, calls, report_text, bool(report_text))
    run: dict[str, Any] = {
        "run_id": meta["run_id"],
        "started_at": meta["started_at"],
        "finished_at": utc_now(),
        "today": meta["today"],
        "leads_file": {
            "path": str(leads_file),
            "sha256_before": sha256_hex(before_raw),
            "sha256_after": after_snapshot.sha256,
            "changed": sha256_hex(before_raw) != after_snapshot.sha256,
        },
        "rules": {"version": rules.version, "sha256": rules.sha256},
        "runtime": {
            "backend": "external-session",
            "model": model,
            "note": "сессия проведена вне раннера: список инструментов модели и телеметрия "
            "рантайма не наблюдались",
        },
        "error": None,
        "reconciliation": reconciliation,
        "metrics": {
            "model_invoked": True,
            "tool_calls": tool_metrics(calls),
            **usage_metrics(None),
        },
    }
    run["status"] = run_status(reconciliation, None)
    (run_dir / "run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "summary.md").write_text(render_summary(run), encoding="utf-8")
    if report_text:
        (run_dir / "model_report.md").write_text(report_text, encoding="utf-8")
    # Снимок «до» — копия данных клиентов, после сверки он не нужен. Но если отчёт модели
    # передан и не разобран, снимок остаётся: сверку можно повторить с исправленным отчётом.
    report_unreadable = bool(report_text) and not reconciliation["model_report_available"]
    run["before_copy_kept"] = keep_before or report_unreadable
    if not run["before_copy_kept"]:
        (run_dir / BEFORE_COPY).unlink()
    run["run_dir"] = str(run_dir)
    return run


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(prog="python -m lead_assistant.session")
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("begin", help="сделать снимок перед сессией")
    start.add_argument("--leads-file", default=DEFAULT_LEADS_FILE)
    start.add_argument("--runs-dir", default="runs")
    start.add_argument("--today", default=date.today().isoformat())

    finish = commands.add_parser("end", help="сверить сессию и построить сводку")
    finish.add_argument("run_dir", type=Path)
    finish.add_argument("--report", type=Path, help="файл с итоговым сообщением модели")
    finish.add_argument("--model", help="модель, которая вела сессию (для записи в run.json)")
    finish.add_argument("--keep-before", action="store_true", help="не удалять снимок «до»")

    args = parser.parse_args(argv)
    try:
        if args.command == "begin":
            meta = begin(
                Path(args.leads_file).expanduser().resolve(),
                Path(args.runs_dir).expanduser().resolve(),
                args.today,
            )
            print(f"Сессия {meta['run_id']}: {meta['run_dir']}")
            for name, value in meta["env"].items():
                print(f'export {name}="{value}"')
            return 0
        report = args.report.read_text(encoding="utf-8") if args.report else ""
        if args.report and not report.strip():
            print(f"ОШИБКА: файл отчёта пуст: {args.report}", file=sys.stderr)
            return 2  # снимок «до» не тронут, команду можно повторить
        run = end(args.run_dir, report, args.model, args.keep_before)
    except (LeadError, OSError) as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        return 2
    print((Path(run["run_dir"]) / "summary.md").read_text(encoding="utf-8"))
    return exit_code(run["status"])


if __name__ == "__main__":
    sys.exit(main())
