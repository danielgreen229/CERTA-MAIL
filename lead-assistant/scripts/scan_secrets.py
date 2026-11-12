"""Проверка файлов, каталогов и архивов на секреты и личные адреса.

    python scripts/scan_secrets.py PATH [PATH ...]

Печатает путь, номер строки и тип находки; само значение не выводится.
Код возврата 1, если что-то найдено.
"""

from __future__ import annotations

import re
import sys
import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path

PATTERNS: dict[str, re.Pattern[str]] = {
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    "bearer_token": re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
    "jwt": re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "oauth_refresh": re.compile(r"(?i)\"?(refresh|access)_?token\"?\s*[:=]\s*\"[^\"]{16,}\""),
    "secret_assignment": re.compile(
        # Значение в кавычках или после «=» без пробелов; ссылки кода на переменные
        # (api_key=options.api_key, os.environ.get(...)) секретом не считаются.
        r"(?i)\b(api[_-]?key|secret|passwd|password|auth[_-]?token)\b\s*[:=]\s*"
        r"(?:[\"'][^\"'\s]{12,}[\"']|(?![A-Za-z_]+[.(])[A-Za-z0-9_\-/+]{16,})"
    ),
}
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9\-]+\.)+[A-Za-z]{2,}")
# Учебные домены из исходных данных и служебные адреса не считаются личными.
SAFE_EMAIL_DOMAINS = ("example.com", ".example", "anthropic.com")
# Заведомо поддельные значения из тестов маскирования секретов.
ALLOWLIST = (
    "sk-ant-api03-abcdefgh12345678",
    "Bearer abc.def.ghi-123456",
    'password="hunter2hunter2"',
    "ANTHROPIC_API_KEY=s3cr3tvalue",
    'api_key="secret-key-value"',
)
SKIP_DIRS = {".venv", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".zip", ".gz", ".exe", ".pyc", ".docx", ".pdf"}


def scan_text(label: str, text: str) -> list[str]:
    findings: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        cleaned = line
        for fake in ALLOWLIST:
            cleaned = cleaned.replace(fake, "")
        for name, pattern in PATTERNS.items():
            if pattern.search(cleaned):
                findings.append(f"{label}:{number}: {name}")
        for match in EMAIL.finditer(cleaned):
            domain = match.group(0).rsplit("@", 1)[1].lower()
            if not any(domain == safe or domain.endswith(safe) for safe in SAFE_EMAIL_DOMAINS):
                findings.append(f"{label}:{number}: personal_email")
    return findings


def iter_texts(path: Path) -> Iterator[tuple[str, str]]:
    """Отдаёт (метка, текст) для файла, каждого файла каталога или каждого члена архива."""
    if path.is_dir():
        for child in sorted(path.rglob("*")):
            if child.is_file() and not SKIP_DIRS.intersection(child.parts):
                yield from iter_texts(child)
        return
    name = path.name.lower()
    if name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                handle = archive.extractfile(member) if member.isfile() else None
                if handle is not None:
                    yield f"{path}!{member.name}", handle.read().decode("utf-8", "replace")
        return
    if name.endswith(".zip"):
        with zipfile.ZipFile(path) as bundle:
            for info in bundle.infolist():
                if not info.is_dir():
                    yield f"{path}!{info.filename}", bundle.read(info).decode("utf-8", "replace")
        return
    if path.suffix.lower() in BINARY_SUFFIXES:
        return
    yield str(path), path.read_bytes().decode("utf-8", "replace")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    findings: list[str] = []
    scanned = 0
    for raw in argv:
        for label, text in iter_texts(Path(raw)):
            scanned += 1
            findings.extend(scan_text(label, text))
    for finding in findings:
        print(finding)
    print(f"проверено файлов: {scanned}; находок: {len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv[1:]))
