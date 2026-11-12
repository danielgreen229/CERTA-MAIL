"""Локальная модель: каталог, загрузка с проверкой контрольной суммы, запуск сервера, выбор."""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
import tarfile
import threading
import zipfile
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lead_assistant import backends, llm


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "llm home"
    monkeypatch.setenv(llm.ENV_HOME, str(directory))
    for name in (llm.ENV_MODEL, llm.ENV_BUILD, backends.ENV_LLM_URL, backends.ENV_BACKEND):
        monkeypatch.delenv(name, raising=False)
    return directory


@pytest.fixture
def file_server(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    """Локальный HTTP-сервер с поддержкой докачки (Range)."""
    root = tmp_path / "served"
    root.mkdir()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            data = (root / self.path.lstrip("/")).read_bytes()
            start = 0
            requested = self.headers.get("Range")
            if requested:
                start = int(requested.split("=")[1].rstrip("-"))
                self.send_response(206)
            else:
                self.send_response(200)
            self.send_header("Content-Length", str(len(data) - start))
            self.end_headers()
            self.wfile.write(data[start:])

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", root
    server.shutdown()
    server.server_close()


def test_catalog_is_pinned() -> None:
    assert llm.DEFAULT_MODEL in llm.MODELS and re.fullmatch(r"b\d+", llm.LLAMA_BUILD)
    artifacts = [spec.artifact for spec in llm.MODELS.values()]
    artifacts += [artifact for group in llm.BUILDS.values() for artifact in group]
    for artifact in artifacts:
        assert re.fullmatch(r"[0-9a-f]{64}", artifact.sha256), artifact.name
        assert artifact.url.startswith("https://") and artifact.url.endswith(artifact.name)
        assert artifact.size_mb > 0
    assert len({artifact.sha256 for artifact in artifacts}) == len(artifacts)
    for platform in ("linux-x64", "win-x64"):
        assert (platform, "cpu") in llm.BUILDS  # сборка без видеокарты есть всегда
    assert {flavor for _platform, flavor in llm.BUILDS} <= set(llm.BUILD_NOTES)
    assert llm.platform_key() in {platform for platform, _flavor in llm.BUILDS}
    assert "cpu" in llm.available_builds()


def test_download_verifies_checksum_and_resumes(
    file_server: tuple[str, Path], tmp_path: Path
) -> None:
    url, root = file_server
    payload = b"model-bytes-" * 5000
    (root / "model.gguf").write_bytes(payload)
    good = llm.Artifact("model.gguf", f"{url}/model.gguf", hashlib.sha256(payload).hexdigest(), 1)
    target = tmp_path / "models" / "model.gguf"

    # Докачка: часть файла уже лежит рядом.
    target.parent.mkdir()
    target.with_name("model.gguf.part").write_bytes(payload[:1234])
    assert llm.download(good, target, echo=lambda _line: None) == target
    assert target.read_bytes() == payload and not target.with_name("model.gguf.part").exists()

    bad = llm.Artifact("model.gguf", f"{url}/model.gguf", "0" * 64, 1)
    other = tmp_path / "other" / "model.gguf"
    with pytest.raises(llm.LlmSetupError, match="контрольная сумма"):
        llm.download(bad, other, echo=lambda _line: None)
    assert not other.exists() and not other.with_name("model.gguf.part").exists()

    missing = llm.Artifact("x", "http://127.0.0.1:9/x", "0" * 64, 1)
    with pytest.raises(llm.LlmSetupError, match="не удалось скачать"):
        llm.download(missing, tmp_path / "x", echo=lambda _line: None)


def _archive(name: str, member: str) -> bytes:
    buffer = io.BytesIO()
    if name.endswith(".zip"):
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr(member, "binary")
    else:
        with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
            info = tarfile.TarInfo(member)
            info.size = 6
            bundle.addfile(info, io.BytesIO(b"binary"))
    return buffer.getvalue()


def test_ensure_server_downloads_extracts_and_reuses(
    home: Path, file_server: tuple[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    url, root = file_server
    binary_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    name = "build.zip" if sys.platform == "win32" else "build.tar.gz"
    data = _archive(name, f"build/bin/{binary_name}")
    (root / name).write_bytes(data)
    artifact = llm.Artifact(name, f"{url}/{name}", hashlib.sha256(data).hexdigest(), 1)
    monkeypatch.setitem(llm.BUILDS, (llm.platform_key(), "cpu"), (artifact,))

    with pytest.raises(llm.LlmSetupError, match="не установлен"):
        llm.ensure_server("cpu", allow_download=False)
    binary = llm.ensure_server("cpu", echo=lambda _line: None)
    assert binary.name == binary_name and binary.is_file() and home in binary.parents
    (root / name).unlink()  # второй вызов не обращается к сети
    assert llm.ensure_server("cpu", echo=lambda _line: None) == binary
    with pytest.raises(llm.LlmSetupError, match="не предусмотрена"):
        llm.ensure_server("quantum")


def test_ensure_model_and_unknown_model(home: Path) -> None:
    with pytest.raises(llm.LlmSetupError, match="неизвестная модель"):
        llm.ensure_model("gpt-9")
    with pytest.raises(llm.LlmSetupError, match="не скачана"):
        llm.ensure_model("qwen3-8b", allow_download=False)
    path = llm.model_path("qwen3-8b")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"weights")
    assert llm.ensure_model("qwen3-8b", allow_download=False) == path
    assert any("qwen3-8b" in line and "скачана" in line for line in llm._status())


FAKE_SERVER = """
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
port = int(sys.argv[sys.argv.index("--port") + 1])
print("fake llama-server starting", flush=True)
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}')
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


def _fake_binary(tmp_path: Path, body: str) -> Path:
    """«llama-server» для теста: сценарий на Python, запускаемый тем же интерпретатором."""
    script = tmp_path / "fake_server.py"
    script.write_text(body, encoding="utf-8")
    return script


def test_server_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = _fake_binary(tmp_path, FAKE_SERVER)
    server = llm.LlamaServer(Path(sys.executable), tmp_path / "model.gguf", tmp_path / "s.log")
    monkeypatch.setattr(
        server, "command", lambda: [sys.executable, str(script), "--port", str(server.port)]
    )
    with server:
        assert server.base_url.startswith("http://127.0.0.1:") and server._healthy()
        process = server._process
    assert process is not None and process.poll() is not None  # остановлен после блока
    assert "fake llama-server starting" in (tmp_path / "s.log").read_text("utf-8")


def test_server_that_dies_reports_its_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = _fake_binary(tmp_path, "import sys; print('error: failed to load model'); sys.exit(3)")
    server = llm.LlamaServer(Path(sys.executable), tmp_path / "m.gguf", tmp_path / "s.log")
    monkeypatch.setattr(server, "command", lambda: [sys.executable, str(script)])
    with pytest.raises(llm.LlmSetupError, match="failed to load model"):
        server.start()


def test_server_command_line(tmp_path: Path) -> None:
    server = llm.LlamaServer(
        tmp_path / "llama-server", tmp_path / "m.gguf", tmp_path / "s.log",
        context=8192, gpu_layers=999, reasoning=True,
    )  # fmt: skip
    server.port = 12345
    command = server.command()

    def value(flag: str) -> str:
        return command[command.index(flag) + 1]

    assert value("--ctx-size") == "8192" and value("--n-gpu-layers") == "999"
    assert value("--host") == "127.0.0.1" and value("--port") == "12345"
    assert value("--reasoning") == "on" and "--jinja" in command and "--no-webui" in command


def parse(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    backends.add_backend_arguments(parser)
    return parser.parse_args(list(argv))


def test_recommended_model_depends_on_memory_and_build(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = llm.total_memory_gb()
    assert memory is None or memory > 0.5
    for gigabytes, expected in ((64.0, "qwen3-14b"), (16.0, "qwen3-8b"), (8.0, "qwen3-4b")):
        monkeypatch.setattr(llm, "total_memory_gb", lambda value=gigabytes: value)
        assert llm.recommended_model("cpu") == expected
        assert llm.recommended_model("vulkan") == "qwen3-14b"  # с видеокартой — прошедшая оценку
    monkeypatch.setattr(llm, "total_memory_gb", lambda: None)
    assert llm.recommended_model("cpu") == "qwen3-14b"


def test_model_choice_precedence(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "total_memory_gb", lambda: 64.0)
    default = backends.options_from_args(parse())
    assert (default.backend, default.model, default.build) == ("local", "qwen3-14b", "cpu")
    assert default.allow_download and not default.reasoning and default.llm_url is None

    backends.save_choice("qwen3-8b", "vulkan")  # выбор, сохранённый установкой
    saved = backends.options_from_args(parse())
    assert (saved.model, saved.build) == ("qwen3-8b", "vulkan")

    monkeypatch.setenv(llm.ENV_MODEL, "qwen3-4b")
    assert backends.options_from_args(parse()).model == "qwen3-4b"

    explicit = backends.options_from_args(parse("--model", "qwen3-8b", "--build", "cpu", "--think"))
    assert (explicit.model, explicit.build, explicit.reasoning) == ("qwen3-8b", "cpu", True)

    external = backends.options_from_args(
        parse("--llm-url", "http://localhost:11434/v1", "--model", "x")
    )
    assert external.llm_url == "http://localhost:11434/v1" and external.model == "x"
    assert backends.options_from_args(parse("--backend", "claude")).model == "claude-opus-5-5"


def test_interactive_choice_is_saved(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "total_memory_gb", lambda: 64.0)
    answers = iter(["3", ""])  # третья модель, сборка по умолчанию
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    options = backends.options_from_args(parse("--choose"))
    assert options.model == "qwen3-14b" and options.build == llm.available_builds()[0]
    assert backends.load_saved() == {"model": "qwen3-14b", "build": options.build}


def test_open_backend_for_external_api(home: Path, tmp_path: Path) -> None:
    options = backends.BackendOptions(
        llm_url="http://localhost:11434/v1", model="llama3", api_key="k"
    )
    with backends.open_backend(options, tmp_path / "log") as backend:
        assert type(backend).__name__ == "LocalLlmBackend"
        assert backend.base_url == "http://localhost:11434/v1"  # type: ignore[attr-defined]
        assert "localhost:11434" in backend.client  # type: ignore[attr-defined]
