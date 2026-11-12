"""Выбор модели при запуске: общие параметры командной строки и создание бэкенда.

Порядок выбора: параметр команды → переменная окружения → сохранённый выбор
(.llm/config.json, его пишет установка) → значение по умолчанию.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from lead_assistant import llm
from lead_assistant.agent import CLAUDE_DEFAULT_MODEL, AgentBackend, ClaudeSdkBackend
from lead_assistant.local_backend import LocalLlmBackend

ENV_BACKEND = "LEADS_BACKEND"
ENV_LLM_URL = "LEADS_LLM_URL"
ENV_LLM_API_KEY = "LEADS_LLM_API_KEY"


@dataclass
class BackendOptions:
    backend: str = "local"
    model: str = llm.DEFAULT_MODEL
    build: str = llm.DEFAULT_BUILD
    llm_url: str | None = None
    api_key: str | None = None
    context: int = llm.DEFAULT_CONTEXT
    reasoning: bool = False
    allow_download: bool = True


def config_path() -> Path:
    return llm.llm_home() / "config.json"


def load_saved() -> dict[str, str]:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return (
        {k: str(v) for k, v in data.items() if k in ("model", "build")}
        if isinstance(data, dict)
        else {}
    )


def save_choice(model: str, build: str) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": model, "build": build}) + "\n", encoding="utf-8")


def add_backend_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("модель")
    group.add_argument(
        "--model",
        help=f"модель: {', '.join(llm.MODELS)} (по умолчанию сохранённый выбор или "
        f"{llm.DEFAULT_MODEL}); для --llm-url и --backend claude — имя модели сервиса",
    )
    group.add_argument(
        "--build",
        help="сборка llama.cpp: cpu, vulkan или cuda (по умолчанию сохранённый выбор или cpu)",
    )
    group.add_argument(
        "--choose", action="store_true", help="выбрать модель и сборку из списка перед запуском"
    )
    group.add_argument(
        "--llm-url",
        default=os.environ.get(ENV_LLM_URL),
        help="адрес готового OpenAI-совместимого API (Ollama, LM Studio, облачный сервис); "
        f"локальный сервер тогда не запускается. Ключ — в переменной {ENV_LLM_API_KEY}",
    )
    group.add_argument("--context", type=int, default=llm.DEFAULT_CONTEXT, help="размер контекста")
    group.add_argument(
        "--think", action="store_true", help="разрешить модели скрытые рассуждения (медленнее)"
    )
    group.add_argument("--no-download", action="store_true", help="не скачивать модель и сервер")
    group.add_argument(
        "--backend",
        choices=("local", "claude"),
        default=os.environ.get(ENV_BACKEND) or "local",
        help="local — бесплатная модель (по умолчанию); claude — Claude Agent SDK, если "
        "установлен пакет и выполнен вход",
    )


def choose_interactively() -> tuple[str, str]:
    """Спрашивает модель и сборку в терминале."""
    models = list(llm.MODELS.values())
    builds = llm.available_builds()
    print("Модель:")
    for number, spec in enumerate(models, start=1):
        present = "скачана" if llm.model_path(spec.key).exists() else "будет скачана"
        size_gb = spec.artifact.size_mb / 1000
        print(
            f"  {number}) {spec.key} — ~{size_gb:.1f} ГБ на диске, ~{spec.memory_gb} ГБ памяти, "
            f"{present}; {spec.note}"
        )
    suggested = llm.recommended_model()
    default = next(i for i, spec in enumerate(models, start=1) if spec.key == suggested)
    model = models[_ask(len(models), default=default) - 1].key
    print("Сборка llama.cpp:")
    for number, flavor in enumerate(builds, start=1):
        print(f"  {number}) {flavor} — {llm.BUILD_NOTES[flavor]}")
    build = builds[_ask(len(builds), default=1) - 1]
    return model, build


def _ask(count: int, default: int) -> int:
    while True:
        answer = input(f"Номер [1-{count}, Enter — {default}]: ").strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= count:
            return int(answer)


def options_from_args(args: argparse.Namespace) -> BackendOptions:
    saved = load_saved()
    build = args.build or os.environ.get(llm.ENV_BUILD) or saved.get("build") or llm.DEFAULT_BUILD
    model = (
        args.model
        or os.environ.get(llm.ENV_MODEL)
        or saved.get("model")
        or llm.recommended_model(build)
    )
    if args.backend == "local" and not args.llm_url and args.choose:
        model, build = choose_interactively()
        save_choice(model, build)
    if args.backend == "claude" and not args.model:
        model = CLAUDE_DEFAULT_MODEL
    return BackendOptions(
        backend=args.backend,
        model=model,
        build=build,
        llm_url=args.llm_url,
        api_key=os.environ.get(ENV_LLM_API_KEY),
        context=args.context,
        reasoning=args.think,
        allow_download=not args.no_download,
    )


@contextlib.contextmanager
def open_backend(
    options: BackendOptions, log_path: Path, echo: llm.Echo = print
) -> Iterator[AgentBackend]:
    """Готовит выбранный бэкенд; локальный сервер модели живёт до выхода из блока."""
    if options.backend == "claude":
        yield ClaudeSdkBackend()
        return
    if options.llm_url:
        host = urlparse(options.llm_url).netloc or options.llm_url
        yield LocalLlmBackend(
            options.llm_url,
            model=options.model,
            client=f"OpenAI-совместимый API ({host})",
            api_key=options.api_key,
        )
        return
    with llm.local_server(
        options.model,
        options.build,
        log_path,
        echo,
        context=options.context,
        allow_download=options.allow_download,
        reasoning=options.reasoning,
    ) as (server, facts):
        yield LocalLlmBackend(
            server.base_url, model=str(facts["model"]), client=str(facts["client"]), facts=facts
        )


def use_utf8_console() -> None:
    """Кириллица в консоли не должна зависеть от локали терминала."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
