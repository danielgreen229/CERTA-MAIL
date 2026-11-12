"""Сборка архива проекта.

    python scripts/make_release.py OUTPUT_DIR

В архив попадают исходники, тесты, правила, конфигурация MCP, зафиксированные
зависимости и оригинал данных. Рабочая копия заявок, окружение, кэши и артефакты
прогонов в архив не входят.
"""

from __future__ import annotations

import hashlib
import io
import sys
import tarfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP_LEVEL = "lead-assistant"

INCLUDE_FILES = (
    "README.md",
    "CLAUDE.md",
    "pyproject.toml",
    "requirements.lock",
    "requirements-dev.lock",
    "requirements-build.in",
    ".mcp.json",
    ".gitignore",
    ".claude/settings.json",
    ".claude/commands/process-leads.md",
    "data/leads.original.json",
)
INCLUDE_DIRS = ("src", "tests", "scripts", "evals", "docs")
EXCLUDE_PARTS = {"__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".egg-info"}


def collect() -> list[Path]:
    files = [ROOT / name for name in INCLUDE_FILES]
    for directory in INCLUDE_DIRS:
        for path in sorted((ROOT / directory).rglob("*")):
            if not path.is_file() or EXCLUDE_PARTS.intersection(path.parts):
                continue
            if any(part.endswith(".egg-info") for part in path.parts):
                continue
            if path.suffix in EXCLUDE_SUFFIXES:
                continue
            files.append(path)
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise SystemExit(f"не найдены файлы для архива: {missing}")
    return sorted(set(files))


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    output_dir = Path(argv[0]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    version = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    archive_path = output_dir / f"{TOP_LEVEL}-{version}.tar.gz"

    files = collect()
    with tarfile.open(archive_path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            # Текст хранится с LF независимо от системы, на которой собран архив.
            data = path.read_bytes().replace(b"\r\n", b"\n")
            info = tarfile.TarInfo(f"{TOP_LEVEL}/{relative}")
            info.size = len(data)
            info.mtime = int(path.stat().st_mtime)
            info.mode = 0o755 if relative.endswith(".sh") else 0o644
            archive.addfile(info, io.BytesIO(data))

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (output_dir / f"{archive_path.name}.sha256").write_text(
        f"{digest}  {archive_path.name}\n", encoding="utf-8"
    )
    print(f"{archive_path}  файлов: {len(files)}  sha256: {digest}")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv[1:]))
