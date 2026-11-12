"""Локальная бесплатная модель: каталог, загрузка с проверкой контрольных сумм, запуск сервера.

Используется сервер llama.cpp (llama-server) с OpenAI-совместимым API и открытые модели
в формате GGUF. Всё ставится в каталог проекта (.llm/), без root и без регистрации.

    python -m lead_assistant.llm list                       # что можно выбрать
    python -m lead_assistant.llm install --model qwen3-8b --build cpu
    python -m lead_assistant.llm status
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LLAMA_BUILD = "b12110"
_RELEASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}/"
ENV_HOME = "LEADS_LLM_HOME"
ENV_MODEL = "LEADS_LLM_MODEL"
ENV_BUILD = "LEADS_LLM_BUILD"
DEFAULT_MODEL = "qwen3-14b"
DEFAULT_BUILD = "cpu"
DEFAULT_CONTEXT = 16384

type Echo = Callable[[str], None]


class LlmSetupError(Exception):
    """Локальную модель не удалось подготовить или запустить."""


@dataclass(frozen=True)
class Artifact:
    name: str
    url: str
    sha256: str
    size_mb: int


@dataclass(frozen=True)
class ModelSpec:
    key: str
    artifact: Artifact
    title: str
    memory_gb: int
    note: str


def _model(
    key: str, repo: str, file: str, sha256: str, size_mb: int, title: str, memory_gb: int, note: str
) -> ModelSpec:
    url = f"https://huggingface.co/{repo}/resolve/main/{file}"
    return ModelSpec(key, Artifact(file, url, sha256, size_mb), title, memory_gb, note)


# Открытые модели Qwen3 (лицензия Apache-2.0), квантизация Q4_K_M.
MODELS: dict[str, ModelSpec] = {
    spec.key: spec
    for spec in (
        _model(
            "qwen3-4b",
            "Qwen/Qwen3-4B-GGUF",
            "Qwen3-4B-Q4_K_M.gguf",
            "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5",
            2500,
            "Qwen3 4B",
            6,
            "для слабого сервера; выше риск ошибок в приоритетах и формулировках",
        ),
        _model(
            "qwen3-8b",
            "Qwen/Qwen3-8B-GGUF",
            "Qwen3-8B-Q4_K_M.gguf",
            "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785",
            5030,
            "Qwen3 8B",
            10,
            "для сервера без видеокарты; ошибается в части классификаций",
        ),
        _model(
            "qwen3-14b",
            "Qwen/Qwen3-14B-GGUF",
            "Qwen3-14B-Q4_K_M.gguf",
            "500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0",
            9000,
            "Qwen3 14B",
            17,
            "проходит набор для оценки; нужна видеокарта от 12 ГБ или много памяти и времени",
        ),
    )
}


def _build(name: str, sha256: str, size_mb: int) -> Artifact:
    return Artifact(name, _RELEASE + name, sha256, size_mb)


# Официальные сборки llama.cpp. Ключ: (платформа, вариант).
BUILDS: dict[tuple[str, str], tuple[Artifact, ...]] = {
    ("linux-x64", "cpu"): (
        _build(
            f"llama-{LLAMA_BUILD}-bin-ubuntu-x64.tar.gz",
            "368227edcc229be5f9bed16a2223d79b5e41d0ac2e19bcf5825e82291c060e55",
            23,
        ),
    ),
    ("linux-x64", "vulkan"): (
        _build(
            f"llama-{LLAMA_BUILD}-bin-ubuntu-vulkan-x64.tar.gz",
            "a5d741940956ec62e8783aee7e5a4c7c761af867d6f027c3277a51e1a3ac59b0",
            36,
        ),
    ),
    ("linux-x64", "cuda"): (
        _build(
            f"llama-{LLAMA_BUILD}-bin-ubuntu-cuda-12.8-x64.tar.gz",
            "4af1e1da23661db4a5b84b29aae16ebc053df689c5b8b1427c4670f2c6406d8c",
            187,
        ),
        _build(
            f"cudart-llama-{LLAMA_BUILD}-bin-ubuntu-cuda-12.8-x64.tar.gz",
            "6f1d562086d84ae85df880d3711079ec225602b51d530608e5001600625067dd",
            594,
        ),
    ),
    ("linux-arm64", "cpu"): (
        _build(
            f"llama-{LLAMA_BUILD}-bin-ubuntu-arm64.tar.gz",
            "4758b51335e37b4346251f2687d64841ff1c07ecb27fc46323945bb2ec9c44d2",
            19,
        ),
    ),
    ("win-x64", "cpu"): (
        _build(
            f"llama-{LLAMA_BUILD}-bin-win-cpu-x64.zip",
            "98901e327c252875accaf2d1bf364e10e868843b0b63468baad1aa945cdc5da2",
            25,
        ),
    ),
    ("win-x64", "vulkan"): (
        _build(
            f"llama-{LLAMA_BUILD}-bin-win-vulkan-x64.zip",
            "9732a5e48887ca54d0bfe4af4324dc85fd56cd8cda19b52df3542fa6ebe6874f",
            38,
        ),
    ),
}
BUILD_NOTES = {
    "cpu": "без видеокарты; работает везде",
    "vulkan": "видеокарта через Vulkan (NVIDIA, AMD, Intel); нужен драйвер с поддержкой Vulkan",
    "cuda": "видеокарта NVIDIA через CUDA 12.8; библиотеки CUDA скачиваются вместе со сборкой",
}


def open_url(request: urllib.request.Request | str, timeout: float) -> Any:
    """Открывает адрес. К серверу на этой же машине обращаемся напрямую, минуя прокси."""
    url = request if isinstance(request, str) else request.full_url
    host = urllib.parse.urlparse(url).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1"):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def total_memory_gb() -> float | None:
    """Объём оперативной памяти машины; None, если определить не удалось."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = (
                    ("length", ctypes.c_ulong),
                    ("load", ctypes.c_ulong),
                    ("total", ctypes.c_ulonglong),
                    ("free", ctypes.c_ulonglong),
                    ("rest", ctypes.c_ulonglong * 5),
                )

            status = MemoryStatus()
            status.length = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return float(status.total) / 2**30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (OSError, ValueError, AttributeError):
        return None


def recommended_model(build: str = DEFAULT_BUILD) -> str:
    """Модель по умолчанию для этой машины.

    Сборке с видеокартой рекомендуется модель, прошедшая оценку. Без видеокарты большая
    модель при нехватке памяти уходит в подкачку, поэтому выбор зависит от объёма ОЗУ.
    """
    if build != "cpu":
        return DEFAULT_MODEL
    memory = total_memory_gb()
    if memory is None or memory >= 24:
        return DEFAULT_MODEL
    return "qwen3-8b" if memory >= 12 else "qwen3-4b"


def platform_key() -> str:
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if sys.platform == "win32":
        return f"win-{arch}"
    if sys.platform.startswith("linux"):
        return f"linux-{arch}"
    raise LlmSetupError(f"платформа {sys.platform} не поддерживается: задайте --llm-url")


def available_builds() -> list[str]:
    key = platform_key()
    return [flavor for (plat, flavor) in BUILDS if plat == key]


def llm_home() -> Path:
    return Path(os.environ.get(ENV_HOME) or ".llm").expanduser().resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(artifact: Artifact, target: Path, echo: Echo = print) -> Path:
    """Скачивает файл с докачкой и проверкой SHA-256. Готовый файл появляется атомарно."""
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    offset = part.stat().st_size if part.exists() else 0
    request = urllib.request.Request(artifact.url, headers={"User-Agent": "lead-assistant"})
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    echo(f"[загрузка] {artifact.name} (~{artifact.size_mb} МБ) из {artifact.url}")
    try:
        with open_url(request, timeout=60) as response:
            resumed = offset > 0 and response.status == 206
            with part.open("ab" if resumed else "wb") as handle:
                done = offset if resumed else 0
                reported = time.monotonic()
                for chunk in iter(lambda: response.read(1 << 20), b""):
                    handle.write(chunk)
                    done += len(chunk)
                    if time.monotonic() - reported > 15:
                        echo(f"[загрузка] {artifact.name}: {done >> 20} МБ")
                        reported = time.monotonic()
    except (urllib.error.URLError, OSError) as error:
        raise LlmSetupError(
            f"не удалось скачать {artifact.name}: {error}. Повторите команду — загрузка "
            "продолжится с места остановки."
        ) from error
    actual = sha256_file(part)
    if actual != artifact.sha256:
        part.unlink()
        raise LlmSetupError(
            f"контрольная сумма {artifact.name} не совпала: ожидалась {artifact.sha256}, "
            f"получена {actual}. Файл удалён."
        )
    part.replace(target)
    return target


def _extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(target)
    else:
        with tarfile.open(archive) as bundle:
            bundle.extractall(target, filter="data")


def find_server_binary(directory: Path) -> Path | None:
    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    matches = sorted(directory.rglob(name)) if directory.exists() else []
    return matches[0] if matches else None


def build_dir(flavor: str) -> Path:
    return llm_home() / "bin" / f"{LLAMA_BUILD}-{platform_key()}-{flavor}"


def ensure_server(flavor: str, echo: Echo = print, allow_download: bool = True) -> Path:
    """Возвращает путь к llama-server нужной сборки, при необходимости скачивая её."""
    artifacts = BUILDS.get((platform_key(), flavor))
    if artifacts is None:
        raise LlmSetupError(
            f"сборка {flavor!r} для {platform_key()} не предусмотрена; доступны: "
            f"{', '.join(available_builds())}"
        )
    directory = build_dir(flavor)
    binary = find_server_binary(directory)
    if binary is not None:
        return binary
    if not allow_download:
        raise LlmSetupError(
            f"сервер llama.cpp ({flavor}) не установлен: "
            f"python -m lead_assistant.llm install --build {flavor}"
        )
    staging = directory.with_name(directory.name + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    for artifact in artifacts:
        archive = download(artifact, llm_home() / "downloads" / artifact.name, echo)
        _extract(archive, staging)
    binary = find_server_binary(staging)
    if binary is None:
        raise LlmSetupError(f"в архиве сборки {flavor} не найден llama-server")
    if sys.platform != "win32":
        binary.chmod(0o755)
    staging.replace(directory)
    found = find_server_binary(directory)
    assert found is not None
    return found


def model_path(key: str) -> Path:
    return llm_home() / "models" / resolve_model(key).artifact.name


def resolve_model(key: str) -> ModelSpec:
    try:
        return MODELS[key]
    except KeyError:
        raise LlmSetupError(f"неизвестная модель {key!r}; доступны: {', '.join(MODELS)}") from None


def ensure_model(key: str, echo: Echo = print, allow_download: bool = True) -> Path:
    spec = resolve_model(key)
    target = model_path(key)
    if target.exists():
        return target
    if not allow_download:
        raise LlmSetupError(
            f"модель {key} не скачана: python -m lead_assistant.llm install --model {key}"
        )
    return download(spec.artifact, target, echo)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class LlamaServer:
    """Запускает llama-server на время прогона и останавливает его после."""

    def __init__(
        self,
        binary: Path,
        model: Path,
        log_path: Path,
        context: int = DEFAULT_CONTEXT,
        gpu_layers: int = 0,
        startup_timeout: float = 600.0,
        reasoning: bool = False,
        extra_args: tuple[str, ...] = (),
    ) -> None:
        self.binary = binary
        self.model = model
        self.log_path = log_path
        self.context = context
        self.gpu_layers = gpu_layers
        self.startup_timeout = startup_timeout
        self.reasoning = reasoning  # скрытые рассуждения модели: точнее, но заметно медленнее
        self.extra_args = extra_args
        self.port = 0
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def command(self) -> list[str]:
        return [
            str(self.binary),
            "--model", str(self.model),
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "--ctx-size", str(self.context),
            "--n-gpu-layers", str(self.gpu_layers),
            "--parallel", "1",
            "--jinja",  # шаблон чата модели: без него нет вызова инструментов
            "--reasoning", "on" if self.reasoning else "off",
            "--no-webui",
            *self.extra_args,
        ]  # fmt: skip

    def start(self) -> None:
        self.port = _free_port()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        if sys.platform != "win32":
            # Библиотеки сборки (и CUDA, если она скачана) лежат в каталогах самой сборки.
            root = self.binary.parent
            for parent in self.binary.parents:
                if parent.parent.name == "bin" and parent.parent.parent == llm_home():
                    root = parent
            folders = sorted({str(path.parent) for path in root.rglob("*.so*")} | {str(root)})
            env["LD_LIBRARY_PATH"] = ":".join([*folders, env.get("LD_LIBRARY_PATH", "")])
        with self.log_path.open("wb") as log:
            try:
                self._process = subprocess.Popen(
                    self.command(), stdout=log, stderr=subprocess.STDOUT, env=env
                )
            except OSError as error:
                raise LlmSetupError(f"llama-server не запускается: {error}") from error
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise LlmSetupError(
                    f"llama-server завершился с кодом {self._process.returncode}: "
                    f"{self._log_tail()}"
                )
            if self._healthy():
                return
            time.sleep(0.5)
        self.stop()
        raise LlmSetupError(
            f"llama-server не ответил за {self.startup_timeout:.0f} с: {self._log_tail()}"
        )

    def _healthy(self) -> bool:
        try:
            with open_url(f"http://127.0.0.1:{self.port}/health", timeout=5) as r:
                return bool(r.status == 200)
        except (urllib.error.URLError, OSError):
            return False

    def _log_tail(self) -> str:
        try:
            lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return " | ".join(line.strip() for line in lines[-6:] if line.strip())[:600]

    def stop(self) -> None:
        if self._process is None or self._process.poll() is not None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=20)

    def __enter__(self) -> LlamaServer:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


@contextlib.contextmanager
def local_server(
    model: str,
    build: str,
    log_path: Path,
    echo: Echo = print,
    context: int = DEFAULT_CONTEXT,
    allow_download: bool = True,
    reasoning: bool = False,
) -> Iterator[tuple[LlamaServer, dict[str, Any]]]:
    """Готовит сборку и модель, запускает сервер и отдаёт его вместе с описанием рантайма."""
    binary = ensure_server(build, echo, allow_download)
    weights = ensure_model(model, echo, allow_download)
    spec = resolve_model(model)
    server = LlamaServer(
        binary,
        weights,
        log_path,
        context=context,
        gpu_layers=0 if build == "cpu" else 999,
        reasoning=reasoning,
    )
    echo(f"[модель] запуск llama.cpp {LLAMA_BUILD} ({build}) с моделью {spec.title}…")
    started = time.monotonic()
    with server:
        facts = {
            "client": f"llama.cpp {LLAMA_BUILD} ({build}, {platform_key()})",
            "model": spec.artifact.name,
            "model_key": spec.key,
            "model_sha256": spec.artifact.sha256,
            "context": context,
            "reasoning": reasoning,
            "load_seconds": round(time.monotonic() - started, 1),
        }
        yield server, facts


def _status() -> list[str]:
    lines = [f"каталог: {llm_home()}", f"платформа: {platform_key()}", "сборки llama.cpp:"]
    for flavor in available_builds():
        binary = find_server_binary(build_dir(flavor))
        lines.append(
            f"  {flavor:<7} {'установлена' if binary else 'нет':<12} {BUILD_NOTES[flavor]}"
        )
    lines.append("модели:")
    for spec in MODELS.values():
        present = "скачана" if model_path(spec.key).exists() else "нет"
        lines.append(
            f"  {spec.key:<10} {present:<8} ~{spec.artifact.size_mb / 1000:.1f} ГБ на диске, "
            f"~{spec.memory_gb} ГБ памяти — {spec.note}"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python -m lead_assistant.llm")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="показать доступные модели и сборки")
    commands.add_parser("status", help="показать, что установлено")
    install = commands.add_parser("install", help="скачать сборку llama.cpp и модель")
    install.add_argument(
        "--model",
        default=os.environ.get(ENV_MODEL),
        help="по умолчанию — рекомендация для этой машины (по объёму памяти и сборке)",
    )
    install.add_argument("--build", default=os.environ.get(ENV_BUILD) or DEFAULT_BUILD)
    install.add_argument(
        "--choose", action="store_true", help="выбрать модель и сборку из списка в терминале"
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            from lead_assistant import backends  # локальный импорт: backends зависит от llm

            model, build = args.model or recommended_model(args.build), args.build
            if args.choose:
                model, build = backends.choose_interactively()
            binary = ensure_server(build)
            weights = ensure_model(model)
            backends.save_choice(model, build)  # дальнейшие запуски используют этот выбор
            print(f"сервер: {binary}")
            print(f"модель: {weights} (sha256 проверена)")
            print(f"выбор сохранён: модель {model}, сборка {build}")
            return 0
        print("\n".join(_status()))
    except LlmSetupError as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
