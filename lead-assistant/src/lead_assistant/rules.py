"""Загрузка правил агента. Один файл правил используется и раннером, и Claude Code."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lead_assistant.storage import sha256_hex

RULES_PATH = Path(__file__).with_name("rules.md")
_VERSION_PATTERN = re.compile(r"^Версия правил:\s*(\S+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Rules:
    path: Path
    text: str
    version: str
    sha256: str


def load_rules(path: Path = RULES_PATH) -> Rules:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    match = _VERSION_PATTERN.search(text)
    if match is None:
        raise ValueError(f"rules file {path} has no 'Версия правил: X.Y.Z' line")
    return Rules(path=path, text=text, version=match.group(1), sha256=sha256_hex(raw))


def operator_prompt(today: str, batch_limit: int | None = None) -> str:
    """Запрос оператора. Дата передаётся явно, чтобы срочность считалась от неё."""
    prompt = f"Обработай новые заявки. Текущая дата: {today}."
    if batch_limit:
        prompt += (
            f" За эту сессию обработай не более {batch_limit} заявок: первые {batch_limit} "
            "из списка list_leads. Остальные оставь в статусе new — их обработает "
            "следующая сессия."
        )
    return prompt
