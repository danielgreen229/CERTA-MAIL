"""Общий слой работы с заявками для MCP-сервера и API.

Обе точки входа проверяют параметры и черновик одними и теми же функциями, поэтому
правила записи результата и правки менеджера не расходятся.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lead_assistant.draft_policy import check_draft
from lead_assistant.models import (
    STATUS_PROCESSED,
    ErrorCode,
    LeadError,
    LeadId,
    validate_update,
)
from lead_assistant.storage import LeadStore, UpdateResult


def record_result(
    store: LeadStore,
    lead_id: LeadId,
    category: object,
    priority: object,
    status: object,
    draft_reply: object,
) -> UpdateResult:
    """Записывает результат AI-обработки: параметры, затем содержание черновика, затем файл."""
    update = validate_update(category, priority, status, draft_reply)
    if update.draft_reply is not None:
        problems = check_draft(update.draft_reply, store.get_lead(lead_id))
        if problems:
            raise LeadError(
                ErrorCode.DRAFT_POLICY,
                "draft_reply states something the lead does not contain; rewrite it "
                "without these statements: " + "; ".join(problems),
                problems=problems,
            )
    return store.update_lead(lead_id, category, priority, status, draft_reply)


@dataclass(frozen=True)
class Correction:
    category: str
    priority: str
    draft_reply: str | None
    warnings: list[str]


def validate_correction(
    lead: dict[str, Any], category: object, priority: object, draft_reply: object
) -> Correction:
    """Проверяет правку менеджера теми же правилами, что и запись агента.

    Менеджер вправе писать о компании то, чего нет в заявке (он знает условия), поэтому
    замечания проверки черновика возвращаются предупреждениями, а не ошибкой.
    """
    update = validate_update(category, priority, STATUS_PROCESSED, draft_reply)
    warnings = check_draft(update.draft_reply, lead) if update.draft_reply else []
    return Correction(update.category, update.priority, update.draft_reply, warnings)
