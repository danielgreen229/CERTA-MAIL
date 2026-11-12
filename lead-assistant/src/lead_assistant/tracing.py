"""Технический трейс в формате JSON Lines.

В трейс попадают только идентификаторы, имена инструментов, коды исходов, длительности и
счётчики. Тексты обращений, черновики и секреты в трейс не пишутся: функции записи
принимают только перечисленные ниже типы значений, а строки дополнительно обрезаются и
проходят маскирование секретов.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_STRING_CHARS = 300

_SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\"?\s*[:=]\s*\"?)[^\s\",]{6,}"),
)


def redact(text: str) -> str:
    """Маскирует строки, похожие на ключи и токены, и ограничивает длину."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    if len(text) > MAX_STRING_CHARS:
        text = text[:MAX_STRING_CHARS] + "…"
    return text


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_clean(item) for item in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    return redact(str(value))


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Tracer:
    """Дописывает события в файл трейса. Безопасен для параллельных процессов:
    каждая запись — одна операция записи в файл, открытый в режиме дополнения."""

    def __init__(self, path: Path | None, run_id: str | None = None, source: str = "") -> None:
        self.path = path
        self.run_id = run_id
        self.source = source
        self._lock = threading.Lock()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, name: str, **fields: Any) -> dict[str, Any]:
        record: dict[str, Any] = {"ts": utc_now(), "event": name}
        if self.run_id:
            record["run_id"] = self.run_id
        if self.source:
            record["source"] = self.source
        record.update(_clean(fields))
        if self.path is not None:
            line = json.dumps(record, ensure_ascii=False) + "\n"
            with self._lock:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
                try:
                    os.write(fd, line.encode("utf-8"))
                finally:
                    os.close(fd)
        return record


def read_trace(path: Path) -> list[dict[str, Any]]:
    """Читает трейс; повреждённые строки пропускаются, чтобы диагностика не падала."""
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            events.append(record)
    return events
