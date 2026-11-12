"""Оценка качества агента.

    python -m lead_assistant.evals synthetic   # прогон фиксированного набора через модель
    python -m lead_assistant.evals real        # сверка обработанных реальных заявок по ID

Обе команды проверяют записанный результат, а не слова модели.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from lead_assistant.backends import (
    add_backend_arguments,
    open_backend,
    options_from_args,
    use_utf8_console,
)
from lead_assistant.llm import LlmSetupError
from lead_assistant.reconcile import id_key
from lead_assistant.runner import RunConfig, run_processing
from lead_assistant.scoring import score_lead, summarize
from lead_assistant.storage import Lead, parse_leads

# Заранее обработанная запись в фикстуре: прогон не должен её менять.
SENTINEL: Lead = {
    "id": 199,
    "date": "2026-11-08",
    "channel": "email",
    "name": "Контрольная запись",
    "contact": "control@example.com",
    "text": "Запись обработана до прогона и не должна измениться.",
    "status": "processed",
    "category": "question",
    "priority": "low",
    "draft_reply": "Контрольный черновик.",
}


def build_fixture(cases: list[dict[str, Any]]) -> list[Lead]:
    leads: list[Lead] = [{"id": case["id"], **case["lead"], "status": "new"} for case in cases]
    leads.append(dict(SENTINEL))
    return leads


def _entries(run: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not run:
        return {}
    return {id_key(entry["id"]): entry for entry in run["reconciliation"]["leads"]}


def _print_results(results: dict[str, dict[str, Any]], summary: dict[str, Any]) -> None:
    for key, value in results.items():
        bad = [c for c in value["checks"] if not c["ok"]]
        mark = "OK  " if value["ok"] else "FAIL"
        notes = "; ".join(f"{c['name']}: {c['detail']}" for c in bad)
        print(f"  {mark} {key:>4}  {notes}")
    print(
        f"Итог: {summary['passed']}/{summary['total']} пройдено; "
        f"не пройдены: {summary['failed_ids'] or 'нет'}; "
        f"критические: {summary['critical_failed_ids'] or 'нет'}"
    )


def write_fixture(spec: dict[str, Any], path: Path) -> None:
    """Записывает фикстуру набора: все примеры в статусе new и контрольная запись."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_fixture(spec["cases"]), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def score_synthetic(spec: dict[str, Any], fixture: Path, run: dict[str, Any]) -> dict[str, Any]:
    """Сверяет обработанную фикстуру с ожиданиями набора."""
    after = {id_key(lead["id"]): lead for lead in parse_leads(fixture.read_bytes())}
    entries = _entries(run)
    results = {
        str(case["id"]): score_lead(
            after.get(id_key(case["id"])), case["expect"], entries.get(id_key(case["id"]))
        )
        for case in spec["cases"]
    }
    results[str(SENTINEL["id"])] = score_lead(
        after.get(id_key(SENTINEL["id"])), {"untouched": True}, None, SENTINEL
    )
    return {
        "kind": "synthetic",
        "cases_version": spec["version"],
        "run_id": run["run_id"],
        "run_status": run["status"],
        "backend": run["runtime"].get("backend"),
        "model": run["runtime"].get("model"),
        "rules_version": run["rules"]["version"],
        "summary": summarize(results),
        "results": results,
    }


def _finish_synthetic(report: dict[str, Any], run_dir: Path) -> int:
    out = run_dir / "eval_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _print_results(report["results"], report["summary"])
    print(f"[оценка] отчёт: {out}")
    passed = not report["summary"]["failed_ids"]
    return 0 if passed and report["run_status"] in ("ok", "ok_with_warnings") else 1


def run_synthetic(args: argparse.Namespace) -> int:
    spec = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    fixture = (
        Path(args.runs_dir).resolve() / "eval-fixtures" / f"leads-eval-v{spec['version']}.json"
    )
    write_fixture(spec, fixture)
    print(f"[оценка] набор v{spec['version']}: {len(spec['cases'])} примеров, дата {spec['today']}")
    options = options_from_args(args)
    runs_dir = Path(args.runs_dir).resolve()
    config = RunConfig(
        leads_file=fixture,
        runs_dir=runs_dir,
        model=options.model,
        today=spec["today"],
        batch_size=args.batch_size,
        save_dialog=args.save_dialog,
    )
    try:
        with open_backend(options, runs_dir / "eval-fixtures" / "llm_server.log") as backend:
            run = asyncio.run(run_processing(config, backend))
    except LlmSetupError as error:
        print(f"[ошибка] модель не запущена: {error}", file=sys.stderr)
        return 2
    return _finish_synthetic(score_synthetic(spec, fixture, run), Path(run["run_dir"]))


def run_fixture(args: argparse.Namespace) -> int:
    spec = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    write_fixture(spec, Path(args.out))
    print(f"фикстура набора v{spec['version']}: {args.out} (дата прогона: {spec['today']})")
    return 0


def run_score(args: argparse.Namespace) -> int:
    """Оценивает уже проведённый прогон по фикстуре (в том числе сессию вне раннера)."""
    spec = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    run_path = Path(args.run)
    run = json.loads(run_path.read_text(encoding="utf-8"))
    return _finish_synthetic(score_synthetic(spec, Path(args.fixture), run), run_path.parent)


def run_real(args: argparse.Namespace) -> int:
    spec = json.loads(Path(args.expectations).read_text(encoding="utf-8"))
    original = {id_key(x["id"]): x for x in parse_leads(Path(args.original).read_bytes())}
    processed = {id_key(x["id"]): x for x in parse_leads(Path(args.processed).read_bytes())}
    run = json.loads(Path(args.run).read_text(encoding="utf-8")) if args.run else None
    entries = _entries(run)
    results: dict[str, dict[str, Any]] = {}
    for raw_id, expect in spec["leads"].items():
        key = id_key(int(raw_id) if raw_id.lstrip("-").isdigit() else raw_id)
        results[raw_id] = score_lead(
            processed.get(key), expect, entries.get(key) if run else None, original.get(key)
        )
        results[raw_id]["ambiguous"] = bool(expect.get("ambiguous"))
    summary = summarize(results)
    summary["ambiguous_ids"] = [key for key, value in results.items() if value.get("ambiguous")]
    report = {
        "kind": "real",
        "expectations_version": spec["version"],
        "run_id": run["run_id"] if run else None,
        "summary": summary,
        "results": results,
    }
    if args.output:
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    _print_results(results, summary)
    print(f"Неоднозначные случаи (допустима вилка): {summary['ambiguous_ids']}")
    return 0 if not summary["failed_ids"] else 1


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(prog="python -m lead_assistant.evals")
    commands = parser.add_subparsers(dest="command", required=True)

    synthetic = commands.add_parser("synthetic", help="прогнать фиксированный набор через модель")
    synthetic.add_argument("--cases", default="evals/cases.json")
    synthetic.add_argument("--runs-dir", default="runs")
    synthetic.add_argument("--batch-size", type=int, default=5)
    synthetic.add_argument("--save-dialog", action="store_true")
    add_backend_arguments(synthetic)
    synthetic.set_defaults(handler=run_synthetic)

    fixture = commands.add_parser("fixture", help="записать фикстуру набора в файл")
    fixture.add_argument("--cases", default="evals/cases.json")
    fixture.add_argument("--out", required=True)
    fixture.set_defaults(handler=run_fixture)

    score = commands.add_parser("score", help="оценить уже проведённый прогон по фикстуре")
    score.add_argument("--cases", default="evals/cases.json")
    score.add_argument("--fixture", required=True)
    score.add_argument("--run", required=True, help="run.json прогона или сессии")
    score.set_defaults(handler=run_score)

    real = commands.add_parser("real", help="сверить обработанные реальные заявки по ID")
    real.add_argument("--expectations", default="evals/real_expectations.json")
    real.add_argument("--original", default="data/leads.original.json")
    real.add_argument("--processed", default="data/leads.json")
    real.add_argument("--run", help="run.json прогона (для проверки пометок менеджеру)")
    real.add_argument("--output", help="куда сохранить отчёт в JSON")
    real.set_defaults(handler=run_real)

    args = parser.parse_args(argv)
    handler = args.handler
    return int(handler(args))


if __name__ == "__main__":
    sys.exit(main())
