"""Предметная модель: допустимые значения, коды ошибок и проверка параметров обновления."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

type LeadId = int | str

# Контракт MCP-сервера: имя, инструменты и переменные окружения запуска.
SERVER_NAME = "leads"
TOOL_NAMES: tuple[str, ...] = ("list_leads", "get_lead", "update_lead")
ENV_LEADS_FILE = "LEADS_FILE"
ENV_TRACE_FILE = "LEADS_TRACE_FILE"
ENV_RUN_ID = "LEADS_RUN_ID"
ENV_LOCK_TIMEOUT = "LEADS_LOCK_TIMEOUT"
ENV_LOG_LEVEL = "LEADS_LOG_LEVEL"

CATEGORIES: tuple[str, ...] = ("sale", "complaint", "question", "spam")
PRIORITIES: tuple[str, ...] = ("high", "medium", "low")
STATUS_NEW = "new"
STATUS_PROCESSED = "processed"
KNOWN_STATUSES: tuple[str, ...] = (STATUS_NEW, STATUS_PROCESSED)

# Единственные поля, которые разрешено менять инструменту update_lead.
EDITABLE_FIELDS: tuple[str, ...] = ("category", "priority", "status", "draft_reply")
MAX_DRAFT_CHARS = 2000


class ErrorCode(StrEnum):
    """Коды ошибок, по которым различаются причины сбоя."""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"  # параметры вызова не прошли проверку
    NOT_FOUND = "NOT_FOUND"  # заявки с таким ID нет
    CONFLICT = "CONFLICT"  # заявка уже не new и значения отличаются
    STORAGE_NOT_FOUND = "STORAGE_NOT_FOUND"  # файл заявок отсутствует
    STORAGE_CORRUPT = "STORAGE_CORRUPT"  # файл не является корректным JSON
    STORAGE_INVALID = "STORAGE_INVALID"  # JSON корректен, но структура заявок нарушена
    DUPLICATE_ID = "DUPLICATE_ID"  # в файле повторяются ID
    LOCK_TIMEOUT = "LOCK_TIMEOUT"  # не удалось получить блокировку записи
    STORAGE_IO = "STORAGE_IO"  # ошибка ввода-вывода, исход записи может быть неизвестен
    DRAFT_POLICY = "DRAFT_POLICY"  # черновик утверждает то, чего нет в заявке


class LeadError(Exception):
    """Ожидаемая ошибка хранилища или проверки с машинным кодом."""

    def __init__(self, code: ErrorCode, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message, **self.details}


@dataclass(frozen=True)
class LeadUpdate:
    """Проверенные значения для перехода new -> processed."""

    category: str
    priority: str
    draft_reply: str | None
    status: str = field(default=STATUS_PROCESSED)

    def as_fields(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "priority": self.priority,
            "status": self.status,
            "draft_reply": self.draft_reply,
        }


def is_valid_lead_id(value: object) -> bool:
    """ID заявки — целое число или непустая строка. bool не считается числом."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and value != ""


def validate_update(
    category: object, priority: object, status: object, draft_reply: object
) -> LeadUpdate:
    """Проверяет параметры update_lead и возвращает нормализованные значения.

    Собирает все нарушения сразу, чтобы вызывающая сторона исправила их за один повтор.
    """
    problems: list[str] = []

    if category not in CATEGORIES:
        problems.append(f"category must be one of {list(CATEGORIES)}, got {category!r}")
    if priority not in PRIORITIES:
        problems.append(f"priority must be one of {list(PRIORITIES)}, got {priority!r}")
    if status != STATUS_PROCESSED:
        problems.append(
            f"status must be {STATUS_PROCESSED!r} (only the new -> processed transition "
            f"is allowed), got {status!r}"
        )

    normalized_draft: str | None = None
    if category == "spam":
        if draft_reply is not None:
            problems.append("draft_reply must be null for category 'spam'")
        if priority in PRIORITIES and priority != "low":
            problems.append("priority must be 'low' for category 'spam'")
    elif not isinstance(draft_reply, str) or not draft_reply.strip():
        problems.append("draft_reply must be a non-empty string for non-spam categories")
    else:
        normalized_draft = draft_reply.strip()
        if len(normalized_draft) > MAX_DRAFT_CHARS:
            problems.append(
                f"draft_reply is too long: {len(normalized_draft)} characters, "
                f"limit is {MAX_DRAFT_CHARS}"
            )

    if problems:
        raise LeadError(ErrorCode.INVALID_ARGUMENT, "; ".join(problems), problems=problems)

    assert isinstance(category, str) and isinstance(priority, str)
    return LeadUpdate(category=category, priority=priority, draft_reply=normalized_draft)
