"""Команда process-leads: штатный запуск обработки новых заявок."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from lead_assistant.agent import AgentOutcome, AgentRequest, ToolCallback
from lead_assistant.backends import (
    add_backend_arguments,
    open_backend,
    options_from_args,
    use_utf8_console,
)
from lead_assistant.llm import LlmSetupError
from lead_assistant.models import ENV_LEADS_FILE
from lead_assistant.runner import RunConfig, exit_code, run_processing

DEFAULT_LEADS_FILE = "data/leads.json"
ENV_RUNS_DIR = "LEADS_RUNS_DIR"

__all__ = ["DEFAULT_LEADS_FILE", "build_parser", "main", "use_utf8_console"]


def _iso_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="process-leads",
        description="Обработать новые заявки: категория, приоритет, черновик ответа, сводка.",
    )
    parser.add_argument(
        "--leads-file",
        default=os.environ.get(ENV_LEADS_FILE) or DEFAULT_LEADS_FILE,
        help=f"путь к JSON с заявками (по умолчанию ${ENV_LEADS_FILE} или {DEFAULT_LEADS_FILE})",
    )
    parser.add_argument(
        "--runs-dir",
        default=os.environ.get(ENV_RUNS_DIR) or "runs",
        help="каталог для артефактов прогонов (по умолчанию runs)",
    )
    parser.add_argument(
        "--today",
        type=_iso_date,
        default=date.today().isoformat(),
        help="дата, от которой считается срочность (YYYY-MM-DD, по умолчанию сегодня)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=5, help="сколько заявок модель разбирает за сессию"
    )
    parser.add_argument("--max-turns", type=int, default=150, help="предел шагов модели в сессии")
    parser.add_argument("--timeout", type=float, default=1800.0, help="предел времени сессии, с")
    parser.add_argument(
        "--save-dialog",
        action="store_true",
        help="сохранить полный диалог с моделью в runs/<id>/dialog.jsonl (содержит тексты заявок)",
    )
    parser.add_argument(
        "--skip-model-if-empty",
        action="store_true",
        help="не запускать модель, если новых заявок нет (для запуска по расписанию)",
    )
    parser.add_argument("--json", action="store_true", help="вывести run.json вместо сводки")
    add_backend_arguments(parser)
    return parser


class NoModelBackend:
    """Заглушка для прогона без модели: раннер не должен к ней обращаться."""

    async def run(self, request: AgentRequest, on_tool: ToolCallback) -> AgentOutcome:
        raise RuntimeError("модель не была запущена для этого прогона")


def has_new_leads(path: Path) -> bool:
    """Быстрая проверка без модели; при любой проблеме с файлом решение оставляем раннеру."""
    try:
        data = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return False  # раннер сам сообщит об ошибке хранилища, модель для этого не нужна
    if not isinstance(data, list):
        return False
    return any(isinstance(lead, dict) and lead.get("status") == "new" for lead in data)


def print_result(run: dict[str, Any]) -> None:
    run_dir = Path(run["run_dir"])
    print()
    print((run_dir / "summary.md").read_text(encoding="utf-8"))
    metrics = run["metrics"]
    tokens = metrics["tokens"] or {}
    cost = metrics["cost"]
    token_text = (
        f"вход {tokens.get('input_tokens')}, выход {tokens.get('output_tokens')}"
        if tokens
        else "нет данных"
    )
    if cost["status"] == "reported":
        cost_text = f"{cost['reported_usd']:.4f} USD (сообщена клиентом)"
    elif cost["status"] == "not_applicable":
        cost_text = "локальная модель, платы за токены нет"
    else:
        cost_text = "нет данных"
    print(
        f"[метрики] длительность {metrics['duration_ms'] / 1000:.1f} с · сессий "
        f"{metrics['sessions']} · вызовов инструментов {metrics['tool_calls']['total']} · "
        f"токены: {token_text} · стоимость: {cost_text}"
    )
    print(f"[файлы] {run_dir}")
    if run["error"]:
        print(
            f"[ошибка] {run['error']['code']} (слой: {run['error']['layer']}): "
            f"{run['error'].get('message') or ''}",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    args = build_parser().parse_args(argv)
    try:
        options = options_from_args(args)
    except LlmSetupError as error:
        print(f"[ошибка] {error}", file=sys.stderr)
        return 2
    config = RunConfig(
        leads_file=Path(args.leads_file).expanduser().resolve(),
        runs_dir=Path(args.runs_dir).expanduser().resolve(),
        model=options.model,
        today=args.today,
        batch_size=args.batch_size,
        max_turns=args.max_turns,
        timeout_seconds=args.timeout,
        save_dialog=args.save_dialog,
        skip_model_if_empty=args.skip_model_if_empty,
    )

    def progress(line: str) -> None:
        print(line, file=sys.stderr if args.json else sys.stdout, flush=True)

    config.runs_dir.mkdir(parents=True, exist_ok=True)
    if args.skip_model_if_empty and not has_new_leads(config.leads_file):
        # По расписанию при пустой очереди сервер модели не поднимается вовсе.
        run = asyncio.run(run_processing(config, NoModelBackend(), echo=progress))
    else:
        with tempfile.NamedTemporaryFile(
            prefix="llm-server-", suffix=".log", dir=config.runs_dir, delete=False
        ) as handle:
            server_log = Path(handle.name)
        try:
            with open_backend(options, server_log, progress) as backend:
                run = asyncio.run(run_processing(config, backend, echo=progress))
        except LlmSetupError as error:
            print(f"[ошибка] модель не запущена: {error}", file=sys.stderr)
            print("Проверьте установку: leads-doctor", file=sys.stderr)
            server_log.unlink(missing_ok=True)
            return 2
        if server_log.stat().st_size:
            server_log.replace(Path(run["run_dir"]) / "llm_server.log")
        else:
            server_log.unlink()
    if args.json:
        print(json.dumps(run, ensure_ascii=False, indent=2))
    else:
        print_result(run)
    return exit_code(run["status"])


if __name__ == "__main__":
    raise SystemExit(main())
