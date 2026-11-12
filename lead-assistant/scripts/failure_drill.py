"""Учебный разбор сбоев: воспроизводит сбой в каждом слое и показывает, как его отличить.

    python scripts/failure_drill.py

Каждый сценарий выполняет настоящий прогон на временной копии исходных данных через
настоящий MCP-сервер (stdio) и разбирает его по трейсу (lead_assistant.diagnose). Модель
заменена воспроизводимым сценарием или поддельным сервисом, чтобы сбой повторялся
одинаково на любой машине и не требовал видеокарты.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.fake_llm import Behaviour, FakeLlm  # noqa: E402
from tests.helpers import Decision, ScriptedBackend, simple_decision  # noqa: E402

from lead_assistant.agent import AgentBackend  # noqa: E402
from lead_assistant.diagnose import HINTS, diagnose  # noqa: E402
from lead_assistant.local_backend import LocalLlmBackend  # noqa: E402
from lead_assistant.runner import RunConfig, run_processing  # noqa: E402
from lead_assistant.storage import Lead, sha256_hex  # noqa: E402

ORIGINAL = ROOT / "data" / "leads.original.json"


def skip_lead_seven(lead: Lead) -> Decision | None:
    return None if lead["id"] == 7 else simple_decision(lead)


def invalid_category_for_four(lead: Lead) -> Decision | None:
    if lead["id"] == 4:
        return Decision("vip", "high", "Вам положена скидка")
    return simple_decision(lead)


def unsupported_claim_for_ten(lead: Lead) -> Decision | None:
    if lead["id"] == 10:
        return Decision("question", "medium", "Да, мы доставляем в Казань за 2 дня.")
    return simple_decision(lead)


def local(url: str) -> LocalLlmBackend:
    return LocalLlmBackend(url, model="drill", client="учебный сервис модели", request_timeout=20)


async def scenario(
    title: str,
    expected_layer: str,
    backend: AgentBackend,
    work: Path,
    corrupt: bool = False,
    mcp: tuple[str, list[str]] | None = None,
) -> bool:
    directory = work / title.replace(" ", "_")
    directory.mkdir()
    leads_file = directory / "leads.json"
    shutil.copyfile(ORIGINAL, leads_file)
    if corrupt:
        leads_file.write_bytes(leads_file.read_bytes()[:-40])
    before = sha256_hex(leads_file.read_bytes())

    config = RunConfig(
        leads_file=leads_file, runs_dir=directory / "runs", today="2026-11-11", mcp_command=mcp
    )
    run: dict[str, Any] = await run_processing(config, backend, echo=lambda _line: None)
    report = diagnose(Path(run["run_dir"]))

    print(f"\n=== {title}")
    print(f"статус прогона: {run['status']}; учёт: {report['counts']}")
    print(f"ошибки инструментов: {report['tool_errors'] or 'нет'}")
    for finding in report["findings"][:3]:
        print(f"  находка: {finding['scope']}: {finding['code']} → слой «{finding['layer']}»")
    if len(report["findings"]) > 3:
        print(f"  … ещё находок: {len(report['findings']) - 3}")
    unchanged = sha256_hex(leads_file.read_bytes()) == before
    print(f"файл изменён: {'нет' if unchanged else 'да'}")
    ok = bool(report["layers"]) and report["layers"][0] == expected_layer
    verdict = "OK" if ok else "FAIL"
    print(f"ожидаемый слой: {expected_layer}; определён: {report['layers']} → {verdict}")
    print(f"что делать: {HINTS[expected_layer]}")
    return ok


async def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    results: list[bool] = []
    with tempfile.TemporaryDirectory(prefix="leads drill ") as tmp:
        work = Path(tmp)

        # Хранилище: повреждённый JSON. Модель не вызывается вовсе.
        results.append(
            await scenario("хранилище повреждённый JSON", "storage", ScriptedBackend(), work, True)
        )
        # Валидация параметров: сервер отклоняет недопустимую категорию.
        results.append(
            await scenario(
                "валидация недопустимая категория",
                "validation",
                ScriptedBackend(decide=invalid_category_for_four),
                work,
            )
        )
        # Валидация содержания: черновик утверждает то, чего нет в заявке.
        results.append(
            await scenario(
                "валидация неподтверждённый черновик",
                "validation",
                ScriptedBackend(decide=unsupported_claim_for_ten),
                work,
            )
        )
        # Модель: инфраструктура исправна, но одна заявка не доведена до записи.
        results.append(
            await scenario(
                "модель пропуск заявки", "model", ScriptedBackend(decide=skip_lead_seven), work
            )
        )
        with FakeLlm() as fake:
            # MCP: сервер не стартует. Рабочий бэкенд останавливается до обращения к модели.
            broken = (sys.executable, ["-m", "lead_assistant.absent"])
            results.append(
                await scenario("MCP сервер не стартует", "mcp", local(fake.url), work, mcp=broken)
            )
            print(f"обращений к модели: {len(fake.behaviour.requests)}")
        # Рантайм: сервер модели недоступен.
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        results.append(
            await scenario(
                "рантайм сервер модели недоступен",
                "runtime",
                local(f"http://127.0.0.1:{port}/v1"),
                work,
            )
        )
        # Авторизация: внешний сервис модели отклоняет ключ.
        with FakeLlm(Behaviour(http_status=401)) as denied:
            results.append(
                await scenario(
                    "авторизация сервис отклонил ключ", "authorization", local(denied.url), work
                )
            )

    print(f"\nИТОГ: сценариев {len(results)}, слой определён верно в {sum(results)}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
