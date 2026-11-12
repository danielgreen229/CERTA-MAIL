"""Проверка результата обработки по ожиданиям (набор для оценки и сверка реальных заявок).

Чистые функции: заявка после обработки + ожидание -> список проверок. Каждая проверка
ссылается на то, что можно увидеть в исходном тексте или в записанном результате.
"""

from __future__ import annotations

import re
from typing import Any

from lead_assistant.draft_policy import check_draft, detect_language
from lead_assistant.models import STATUS_PROCESSED
from lead_assistant.storage import Lead

# Проверки, провал которых считается критическим: неверная классификация там, где
# ожидание однозначно, и неподтверждённые обещания в черновике.
CRITICAL_CHECKS = frozenset(
    {"processed", "category", "priority", "draft_null", "no_unsupported_claims", "draft_policy"}
)


# Уточнение может быть вопросом или вежливой просьбой («уточните, пожалуйста, маршрут»).
_CLARIFYING_REQUEST = re.compile(
    r"\b(уточните|подскажите|сообщите|укажите|напишите|пришлите|расскажите)\b"
    r"|\b(could you|can you|please (tell|let|specify|share|provide|clarify))\b",
    re.IGNORECASE,
)


def asks_for_details(draft: str) -> bool:
    """Есть ли в черновике уточняющий вопрос или просьба сообщить недостающие данные."""
    return "?" in draft or _CLARIFYING_REQUEST.search(draft) is not None


def _check(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "critical": name in CRITICAL_CHECKS}


def score_lead(
    lead: Lead | None,
    expect: dict[str, Any],
    run_entry: dict[str, Any] | None = None,
    original: Lead | None = None,
) -> dict[str, Any]:
    """Сверяет одну заявку с ожиданием. run_entry — запись заявки из run.json."""
    checks: list[dict[str, Any]] = []
    if lead is None:
        return {"ok": False, "checks": [_check("processed", False, "заявка отсутствует в файле")]}

    if expect.get("untouched"):
        checks.append(_check("untouched", lead == original, "запись должна совпадать с оригиналом"))
        return {"ok": all(c["ok"] for c in checks), "checks": checks}

    checks.append(
        _check("processed", lead.get("status") == STATUS_PROCESSED, str(lead.get("status")))
    )
    for name in ("category", "priority"):
        allowed = expect.get(name)
        if allowed:
            actual = lead.get(name)
            checks.append(
                _check(name, actual in allowed, f"получено {actual!r}, допустимо {allowed}")
            )

    draft_expect = expect.get("draft") or {}
    draft = lead.get("draft_reply")
    if draft_expect.get("null"):
        checks.append(_check("draft_null", draft is None, "для спама черновик должен быть null"))
    elif draft is None and draft_expect.get("allow_null"):
        pass  # допустимый исход: заявка признана спамом
    elif not isinstance(draft, str) or not draft.strip():
        checks.append(_check("draft_present", False, "ожидался непустой черновик"))
    else:
        language = draft_expect.get("language")
        if language:
            actual_language = detect_language(draft)
            checks.append(
                _check(
                    "draft_language",
                    actual_language == language,
                    f"язык черновика: {actual_language}",
                )
            )
        if draft_expect.get("needs_question"):
            checks.append(
                _check("clarifying_question", asks_for_details(draft), "ожидался уточняющий вопрос")
            )
        violations = check_draft(draft, lead)
        checks.append(_check("draft_policy", not violations, "; ".join(violations)))
        hits = [
            pattern
            for pattern in draft_expect.get("must_not_match", [])
            if re.search(pattern, draft, re.IGNORECASE)
        ]
        if "must_not_match" in draft_expect:
            checks.append(
                _check(
                    "no_unsupported_claims",
                    not hits,
                    f"запрещённые шаблоны: {hits}" if hits else "",
                )
            )

    if expect.get("flagged"):
        if run_entry is None:
            checks.append(_check("flagged_for_manager", False, "нет итога модели для проверки"))
        else:
            checks.append(
                _check(
                    "flagged_for_manager",
                    bool(run_entry.get("uncertain")),
                    "заявка должна быть передана менеджеру как спорная",
                )
            )
    if lead.get("priority") == "high" and run_entry is not None:
        checks.append(
            _check(
                "high_has_basis",
                bool(run_entry.get("urgency_basis")) and bool(run_entry.get("next_action")),
                "для high нужны основание срочности и ближайшее действие",
            )
        )
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def summarize(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Сводит результаты по ID в итог набора."""
    failed = {key: value for key, value in results.items() if not value["ok"]}
    critical = sorted(
        key
        for key, value in failed.items()
        if any(not c["ok"] and c["critical"] for c in value["checks"])
    )
    return {
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed_ids": sorted(failed, key=lambda item: (len(item), item)),
        "critical_failed_ids": critical,
    }
