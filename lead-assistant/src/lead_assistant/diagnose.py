"""Разбор прогона по трейсу: в каком слое возник сбой.

    python -m lead_assistant.diagnose runs/<run_id>

Порядок разбора: сначала данные и трейс (хранилище, MCP, валидация, авторизация), и
только если они чисты — поведение модели и правила.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from lead_assistant.backends import use_utf8_console
from lead_assistant.runner import error_layer
from lead_assistant.tracing import read_trace

HINTS = {
    "authorization": "Сервис модели отклонил ключ или вход (модель не вызывалась). Для локальной "
    "модели ключ не нужен; для --llm-url проверьте LEADS_LLM_API_KEY.",
    "mcp": "MCP-сервер не подключился или набор инструментов отличается. Проверьте leads-doctor "
    "и stderr сервера; правила агента менять не нужно.",
    "validation": "Сервер отклонил параметры вызова. Смотрите код и поле problems в ответе "
    "инструмента; если модель повторяет ошибку — уточните правило, иначе это данные.",
    "storage": "Проблема с файлом заявок или блокировкой. Проверьте JSON "
    "(python -m lead_assistant.verify), права на каталог и чужие процессы.",
    "model": "Инфраструктура исправна, заявка не доведена моделью. Повторите прогон; сверьте с "
    "набором для оценки (python -m lead_assistant.evals synthetic), попробуйте модель "
    "крупнее (--model) и только при подтверждении правьте rules.md.",
    "runtime": "Сервер модели не ответил, упал или вышло время. Смотрите llm_server.log в "
    "каталоге прогона и leads-doctor --live; повтор прогона безопасен.",
}


def diagnose(run_dir: Path) -> dict[str, Any]:
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    runner_events = read_trace(run_dir / "trace.jsonl")
    server_events = read_trace(run_dir / "mcp_trace.jsonl")
    runner_calls = [e for e in runner_events if e["event"] == "tool_call"]
    server_calls = [e for e in server_events if e["event"] == "tool_call"]

    findings: list[dict[str, str]] = []
    if run["error"]:
        code = run["error"]["code"]
        findings.append({"scope": "прогон", "code": code, "layer": error_layer(code)})
    # Если прогон упал целиком, необработанные заявки — следствие, а не отдельные сбои модели.
    root_layer = error_layer(run["error"]["code"]) if run["error"] else None
    for failed in run["reconciliation"]["failed"]:
        findings.append(
            {
                "scope": f"заявка {failed['id']}",
                "code": failed["reason"],
                "layer": root_layer or error_layer(failed["reason"]),
            }
        )
    for problem in run["reconciliation"]["integrity_violations"]:
        findings.append({"scope": "целостность", "code": problem, "layer": "storage"})
    for problem in run["reconciliation"]["report_mismatches"]:
        findings.append({"scope": "итог модели", "code": problem, "layer": "model"})

    # Вызов, который видел раннер, но не видел сервер (или наоборот), указывает на транспорт.
    runner_by_tool = Counter(e["tool"] for e in runner_calls)
    server_by_tool = Counter(e["tool"] for e in server_calls)
    if server_events and runner_by_tool != server_by_tool:
        findings.append(
            {
                "scope": "транспорт MCP",
                "code": "CALL_COUNT_MISMATCH "
                f"runner={dict(runner_by_tool)} server={dict(server_by_tool)}",
                "layer": "mcp",
            }
        )
    return {
        "run_id": run["run_id"],
        "status": run["status"],
        "model": run["runtime"].get("model"),
        "rules_version": run["rules"]["version"],
        "counts": run["reconciliation"]["counts"],
        "tool_calls_runner": dict(runner_by_tool),
        "tool_calls_server": dict(server_by_tool),
        "tool_errors": dict(Counter(e["code"] for e in runner_calls if e.get("ok") is False)),
        "server_errors": dict(Counter(e["code"] for e in server_calls if e.get("ok") is False)),
        "findings": findings,
        "layers": sorted({f["layer"] for f in findings}),
    }


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(prog="python -m lead_assistant.diagnose")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = diagnose(args.run_dir)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(
        f"Прогон {result['run_id']}: статус {result['status']}, модель {result['model']}, "
        f"правила {result['rules_version']}"
    )
    print(f"Учёт: {result['counts']}")
    print(
        f"Вызовы (раннер): {result['tool_calls_runner']}  ошибки: {result['tool_errors'] or 'нет'}"
    )
    print(
        f"Вызовы (сервер): {result['tool_calls_server']}  "
        f"ошибки: {result['server_errors'] or 'нет'}"
    )
    if not result["findings"]:
        print("Сбоев не найдено.")
        return 0
    print("Находки:")
    for finding in result["findings"]:
        print(f"  - {finding['scope']}: {finding['code']} → слой «{finding['layer']}»")
    print("Что делать:")
    for layer in result["layers"]:
        print(f"  [{layer}] {HINTS[layer]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
