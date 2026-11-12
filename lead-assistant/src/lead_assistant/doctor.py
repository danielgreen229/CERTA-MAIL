"""Проверка установки: окружение, файл заявок, MCP через stdio, локальная модель.

leads-doctor                # без запуска модели
leads-doctor --live         # плюс короткий реальный прогон: модель вызывает list_leads
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from importlib import metadata
from pathlib import Path

from lead_assistant import llm
from lead_assistant.agent import mcp_server_command
from lead_assistant.backends import (
    BackendOptions,
    add_backend_arguments,
    open_backend,
    options_from_args,
    use_utf8_console,
)
from lead_assistant.cli import DEFAULT_LEADS_FILE
from lead_assistant.models import ENV_LEADS_FILE, ENV_LOG_LEVEL, TOOL_NAMES, LeadError
from lead_assistant.rules import load_rules
from lead_assistant.runner import RunConfig, run_processing
from lead_assistant.storage import LeadStore

type Check = tuple[str, bool | None, str]  # None — справка, не ошибка


def check_environment() -> list[Check]:
    checks: list[Check] = [
        (
            "Python >= 3.12",
            sys.version_info >= (3, 12),
            f"{sys.version.split()[0]} ({sys.executable})",
        )
    ]
    for package in ("mcp", "pydantic"):
        try:
            checks.append((f"пакет {package}", True, metadata.version(package)))
        except metadata.PackageNotFoundError:
            checks.append(
                (f"пакет {package}", False, "не установлен: pip install -r requirements.lock")
            )
    try:
        rules = load_rules()
        checks.append(
            ("правила агента", True, f"версия {rules.version}, sha256 {rules.sha256[:12]}")
        )
    except (OSError, ValueError) as error:
        checks.append(("правила агента", False, str(error)))
    return checks


def check_leads_file(path: Path) -> list[Check]:
    try:
        snapshot = LeadStore(path).snapshot()
    except LeadError as error:
        return [("файл заявок", False, f"{error.code.value}: {error.message}")]
    statuses: dict[str, int] = {}
    for lead in snapshot.leads:
        statuses[lead["status"]] = statuses.get(lead["status"], 0) + 1
    writable = os.access(path.parent, os.W_OK)
    return [
        ("файл заявок", True, f"{path} — заявок {len(snapshot.leads)}, статусы {statuses}"),
        ("каталог данных доступен для записи", writable, str(path.parent)),
    ]


async def _list_tools_over_stdio(path: Path) -> list[str]:
    from mcp import Client, StdioServerParameters

    command, args = mcp_server_command()
    # Журнал сервера в выводе проверки не нужен: оставляем только предупреждения.
    env = {ENV_LEADS_FILE: str(path), ENV_LOG_LEVEL: "WARNING"}
    params = StdioServerParameters(command=command, args=args, env=env)
    async with Client(params) as client:
        tools = await client.list_tools()
        return sorted(tool.name for tool in tools.tools)


def check_mcp(path: Path) -> list[Check]:
    try:
        tools = asyncio.run(asyncio.wait_for(_list_tools_over_stdio(path), timeout=60))
    except Exception as error:  # проверка установки сообщает о любой причине отказа
        return [("MCP-сервер через stdio", False, f"{type(error).__name__}: {error}")]
    ok = tools == sorted(TOOL_NAMES)
    return [("MCP-сервер через stdio", ok, f"инструменты: {', '.join(tools)}")]


def check_model(options: BackendOptions) -> list[Check]:
    """Проверяет, что выбранная модель и сборка сервера на месте."""
    if options.backend == "claude":
        try:
            version = metadata.version("claude-agent-sdk")
        except metadata.PackageNotFoundError:
            hint = "pip install 'lead-assistant[claude]' и вход в Claude"
            return [("бэкенд claude", False, hint)]
        return [("бэкенд claude", None, f"claude-agent-sdk {version}; вход проверяется --live")]
    if options.llm_url:
        return [("модель", None, f"внешний API {options.llm_url}; проверяется --live")]
    try:
        spec = llm.resolve_model(options.model)
        if options.build not in llm.available_builds():
            raise llm.LlmSetupError(
                f"сборка {options.build!r} недоступна для {llm.platform_key()}; "
                f"есть: {', '.join(llm.available_builds())}"
            )
    except llm.LlmSetupError as error:
        return [("модель", False, str(error))]
    binary = llm.find_server_binary(llm.build_dir(options.build))
    weights = llm.model_path(options.model)
    hint = f"python -m lead_assistant.llm install --model {options.model} --build {options.build}"
    return [
        (
            f"сервер llama.cpp {llm.LLAMA_BUILD} ({options.build})",
            binary is not None,
            str(binary) if binary else f"не установлен: {hint}",
        ),
        (
            f"модель {spec.key}",
            weights.exists(),
            f"{weights} (~{spec.artifact.size_mb / 1000:.1f} ГБ)"
            if weights.exists()
            else f"не скачана: {hint}",
        ),
    ]


def check_live(options: BackendOptions) -> list[Check]:
    """Короткий реальный прогон: модель должна вызвать list_leads и найти ноль новых заявок."""
    with tempfile.TemporaryDirectory(prefix="leads-doctor-") as tmp:
        fixture = Path(tmp) / "leads.json"
        fixture.write_text(
            '[\n  {"id": 1, "text": "doctor", "status": "processed"}\n]\n', encoding="utf-8"
        )
        config = RunConfig(
            leads_file=fixture, runs_dir=Path(tmp) / "runs", max_turns=10, timeout_seconds=600
        )
        try:
            with open_backend(options, Path(tmp) / "llm_server.log", lambda _line: None) as backend:
                run = asyncio.run(run_processing(config, backend, echo=lambda _line: None))
        except llm.LlmSetupError as setup_error:
            return [("реальный вызов модели", False, str(setup_error))]
    failure = run["error"]
    if failure:
        detail = f"{failure['code']} (слой: {failure['layer']})"
        return [("реальный вызов модели", False, detail)]
    called = run["metrics"]["tool_calls"]["by_tool"].get("list_leads", 0)
    return [
        (
            "реальный вызов модели",
            called >= 1 and run["status"] in ("ok", "ok_with_warnings"),
            f"{run['runtime'].get('client')}, модель {run['runtime'].get('model')}, "
            f"вызовов list_leads: {called}, инструменты модели: {run['runtime'].get('tools')}",
        )
    ]


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(prog="leads-doctor", description="Проверка установки.")
    parser.add_argument(
        "--leads-file", default=os.environ.get(ENV_LEADS_FILE) or DEFAULT_LEADS_FILE
    )
    parser.add_argument(
        "--live", action="store_true", help="выполнить короткий реальный прогон с моделью"
    )
    add_backend_arguments(parser)
    args = parser.parse_args(argv)
    path = Path(args.leads_file).expanduser().resolve()
    options = options_from_args(args)

    checks = check_environment() + check_leads_file(path) + check_mcp(path) + check_model(options)
    if args.live:
        checks += check_live(options)
    for name, ok, detail in checks:
        mark = "OK  " if ok else ("INFO" if ok is None else "FAIL")
        print(f"[{mark}] {name}: {detail}")
    failed = [name for name, ok, _ in checks if ok is False]
    print("Итог: " + ("готово к работе" if not failed else f"не пройдено: {', '.join(failed)}"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
