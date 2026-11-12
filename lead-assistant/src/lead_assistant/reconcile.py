"""Независимая сверка прогона.

Чистые функции: на входе состояние файла до и после, наблюдавшиеся вызовы инструментов
и итог модели; на выходе — учёт каждой заявки по ID. Счётчики сводки берутся отсюда,
а не из слов модели: результат засчитывается по подтверждённому состоянию файла.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from lead_assistant.agent import ToolCall
from lead_assistant.models import (
    CATEGORIES,
    EDITABLE_FIELDS,
    PRIORITIES,
    STATUS_NEW,
    STATUS_PROCESSED,
    LeadId,
    is_valid_lead_id,
)
from lead_assistant.storage import Lead, sha256_hex

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def id_key(lead_id: LeadId) -> str:
    """Ключ, различающий 1 и "1"."""
    return f"{type(lead_id).__name__}:{lead_id}"


def _digest(value: Any) -> str:
    return sha256_hex(json.dumps(value, ensure_ascii=False, sort_keys=False).encode("utf-8"))


def immutable_part(lead: Lead) -> dict[str, Any]:
    return {key: value for key, value in lead.items() if key not in EDITABLE_FIELDS}


def check_integrity(
    before: list[Lead],
    after: list[Lead],
    scope: Iterable[LeadId],
    allow_additions: bool = False,
) -> list[str]:
    """Проверяет сохранность данных. scope — ID, которые прогон имел право изменить.

    allow_additions разрешает появление новых заявок: файл живой, и CRM может дописать
    запись во время прогона. Исчезновение и перестановка существующих — всегда нарушение.
    """
    problems: list[str] = []
    before_keys = [id_key(lead["id"]) for lead in before]
    after_keys = [id_key(lead["id"]) for lead in after]
    if allow_additions:
        known = set(before_keys)
        after_keys = [key for key in after_keys if key in known]
    if len(before_keys) != len(after_keys):
        problems.append(f"COUNT_CHANGED: {len(before)} -> {len(after)}")
    if before_keys != after_keys:
        problems.append("ORDER_OR_IDS_CHANGED")
    after_by_key = {id_key(lead["id"]): lead for lead in after}
    allowed = {id_key(i) for i in scope}
    for lead in before:
        key = id_key(lead["id"])
        current = after_by_key.get(key)
        if current is None:
            problems.append(f"LEAD_MISSING: {lead['id']!r}")
            continue
        if _digest(immutable_part(lead)) != _digest(immutable_part(current)):
            problems.append(f"IMMUTABLE_FIELDS_CHANGED: {lead['id']!r}")
        if list(immutable_part(lead)) != list(immutable_part(current)):
            problems.append(f"FIELD_ORDER_CHANGED: {lead['id']!r}")
        if key not in allowed and _digest(lead) != _digest(current):
            problems.append(f"OUT_OF_SCOPE_LEAD_CHANGED: {lead['id']!r}")
    return problems


def check_processed_shape(lead: Lead) -> list[str]:
    """Проверяет, что обработанная заявка удовлетворяет контракту записи."""
    problems: list[str] = []
    if lead.get("category") not in CATEGORIES:
        problems.append(f"INVALID_CATEGORY: {lead['id']!r}")
    if lead.get("priority") not in PRIORITIES:
        problems.append(f"INVALID_PRIORITY: {lead['id']!r}")
    draft = lead.get("draft_reply")
    if "draft_reply" not in lead:
        problems.append(f"DRAFT_FIELD_MISSING: {lead['id']!r}")
    elif lead.get("category") == "spam":
        if draft is not None:
            problems.append(f"SPAM_WITH_DRAFT: {lead['id']!r}")
    elif not isinstance(draft, str) or not draft.strip():
        problems.append(f"EMPTY_DRAFT: {lead['id']!r}")
    return problems


def parse_model_report(final_text: str) -> tuple[dict[str, dict[str, Any]] | None, str | None]:
    """Извлекает структурированный итог модели из последнего блока ```json."""
    blocks = _JSON_BLOCK.findall(final_text)
    if not blocks:
        return None, "REPORT_MISSING"
    try:
        data = json.loads(blocks[-1])
    except json.JSONDecodeError:
        return None, "REPORT_INVALID_JSON"
    entries = data.get("leads") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return None, "REPORT_INVALID_SHAPE"
    report: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not is_valid_lead_id(entry.get("id")):
            return None, "REPORT_INVALID_SHAPE"
        report[id_key(entry["id"])] = entry
    return report, None


def merge_reports(final_texts: list[str]) -> str:
    """Сводит итоги нескольких сессий в один текст с общим блоком json."""
    if len(final_texts) <= 1:
        return final_texts[0] if final_texts else ""
    merged: dict[str, dict[str, Any]] = {}
    summaries: list[str] = []
    for text in final_texts:
        report, _error = parse_model_report(text)
        if report is None:
            continue  # сессия без итога: её заявки останутся без пояснений
        merged.update(report)
        summaries.append(_JSON_BLOCK.sub("", text).strip())
    if not merged:
        return "\n\n".join(final_texts)
    block = json.dumps({"leads": list(merged.values())}, ensure_ascii=False)
    return "\n\n".join(summaries) + f"\n\n```json\n{block}\n```\n"


def find_repeats(leads: list[Lead]) -> dict[str, list[LeadId]]:
    """Находит обращения с одним и тем же контактом: ключ заявки -> ID остальных."""
    by_contact: dict[str, list[LeadId]] = {}
    for lead in leads:
        contact = str(lead.get("contact") or "").strip().lower()
        if contact:
            by_contact.setdefault(contact, []).append(lead["id"])
    repeats: dict[str, list[LeadId]] = {}
    for ids in by_contact.values():
        if len(ids) > 1:
            for lead_id in ids:
                repeats[id_key(lead_id)] = [other for other in ids if other != lead_id]
    return repeats


def _text_or_none(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def reconcile(
    before: list[Lead],
    after: list[Lead],
    calls: list[ToolCall],
    final_text: str,
    model_invoked: bool = True,
) -> dict[str, Any]:
    """Сводит прогон к учёту по ID. Каждая найденная заявка попадает ровно в одну группу."""
    after_by_key = {id_key(lead["id"]): lead for lead in after}

    calls_by_key: dict[str, list[ToolCall]] = {}
    for call in calls:
        if call.lead_id is not None:
            calls_by_key.setdefault(id_key(call.lead_id), []).append(call)

    # Заявки, дописанные в файл после снимка «до». Те, которые модель успела обработать,
    # входят в набор прогона; остальные остаются new до следующего запуска.
    known_keys = {id_key(lead["id"]) for lead in before}
    arrived = [lead["id"] for lead in after if id_key(lead["id"]) not in known_keys]
    arrived_in_run = [
        lead_id
        for lead_id in arrived
        if any(c.tool == "update_lead" for c in calls_by_key.get(id_key(lead_id), []))
    ]
    found: list[LeadId] = [lead["id"] for lead in before if lead["status"] == STATUS_NEW]
    found += arrived_in_run
    found_keys = {id_key(i) for i in found}

    report, report_error = parse_model_report(final_text) if model_invoked else (None, None)
    warnings: list[str] = [report_error] if report_error else []
    if arrived:
        warnings.append(f"NEW_LEADS_ARRIVED_DURING_RUN: {arrived!r}")
    integrity = check_integrity(before, after, found, allow_additions=True)

    repeats = find_repeats(after)
    written: list[LeadId] = []
    already: list[LeadId] = []
    failed: list[dict[str, Any]] = []
    per_lead: list[dict[str, Any]] = []
    mismatches: list[str] = []

    for lead_id in found:
        key = id_key(lead_id)
        current = after_by_key.get(key)
        lead_calls = calls_by_key.get(key, [])
        updates = [c for c in lead_calls if c.tool == "update_lead"]
        was_read = any(c.tool == "get_lead" and c.ok for c in lead_calls)
        entry: dict[str, Any] = {"id": lead_id, "category": None, "priority": None}

        status = current["status"] if current is not None else "missing"
        tool_confirmed = any(c.ok and c.result == "updated" for c in updates)
        if status == STATUS_PROCESSED and current is not None:
            entry["category"] = current.get("category")
            entry["priority"] = current.get("priority")
            integrity.extend(check_processed_shape(current))
            # Неясный исход (ответ потерян или STORAGE_IO): запись засчитывается, если
            # состояние файла совпадает с тем, что этот прогон пытался записать.
            state_confirmed = any(
                (c.ok is None or c.code == "STORAGE_IO")
                and c.args.get("category") == current.get("category")
                and c.args.get("priority") == current.get("priority")
                for c in updates
            )
            if tool_confirmed or state_confirmed:
                written.append(lead_id)
                entry["result"] = "written"
                entry["evidence"] = "tool_confirmed" if tool_confirmed else "state_confirmed"
            else:
                already.append(lead_id)
                entry["result"] = "already_processed"
                entry["evidence"] = "no_update_by_this_run" if not updates else "conflict_or_repeat"
            if not was_read and entry["result"] == "written":
                warnings.append(f"WRITTEN_WITHOUT_READ: {lead_id!r}")
        else:
            if tool_confirmed:
                # Инструмент подтвердил запись, а файл её не содержит.
                integrity.append(f"FALSE_CONFIRMATION: {lead_id!r}")
            codes = [c.code for c in updates if c.code]
            if status != STATUS_NEW:
                reason = f"UNEXPECTED_STATUS:{status}"
            elif codes:
                reason = codes[-1]
            elif updates:
                reason = "UPDATE_RESULT_UNKNOWN"
            elif was_read:
                reason = "NO_UPDATE_ATTEMPT"
            else:
                reason = "NOT_READ"
            entry["result"] = "failed"
            entry["reason"] = reason
            failed.append({"id": lead_id, "reason": reason})

        claimed = report.get(key) if report else None
        if report is not None and claimed is None:
            mismatches.append(f"MISSING_IN_MODEL_REPORT: {lead_id!r}")
        if claimed is not None:
            entry["uncertain"] = bool(claimed.get("uncertain"))
            entry["manager_check"] = _text_or_none(claimed.get("manager_check"))
            entry["urgency_basis"] = _text_or_none(claimed.get("urgency_basis"))
            entry["next_action"] = _text_or_none(claimed.get("next_action"))
            if claimed.get("result") != entry["result"]:
                mismatches.append(
                    f"RESULT_MISMATCH: {lead_id!r} model={claimed.get('result')!r} "
                    f"file={entry['result']!r}"
                )
            # Сравниваем только то, что записал этот прогон: у заявки, обработанной кем-то
            # другим, в файле чужие значения, и расхождение с намерением модели — не ошибка.
            if entry["result"] == "written":
                for name in ("category", "priority"):
                    if claimed.get(name) != entry[name]:
                        mismatches.append(
                            f"{name.upper()}_MISMATCH: {lead_id!r} model={claimed.get(name)!r} "
                            f"file={entry[name]!r}"
                        )
        if (
            entry["result"] == "written"
            and entry.get("priority") == "high"
            and not entry.get("urgency_basis")
        ):
            warnings.append(f"HIGH_WITHOUT_BASIS: {lead_id!r}")
        # Повторные обращения определяет код, а не модель: совпадение контакта однозначно.
        others = repeats.get(key)
        if others:
            listed_ids = ", ".join(map(str, others))
            note = f"Повтор: тот же контакт, что в заявке {listed_ids}; ответьте один раз"
            entry["repeat_of"] = others
            entry["uncertain"] = True
            previous = entry.get("manager_check")
            entry["manager_check"] = f"{previous} {note}." if previous else f"{note}."
        per_lead.append(entry)

    if report is not None:
        mismatches.extend(
            f"EXTRA_IN_MODEL_REPORT: {entry['id']!r}"
            for key, entry in report.items()
            if key not in found_keys
        )

    out_of_scope = sorted(
        {repr(c.lead_id) for c in calls if c.tool == "update_lead" and c.lead_id is not None}
        - {repr(i) for i in found}
    )
    warnings.extend(f"UPDATE_OUTSIDE_RUN_SET: {i}" for i in out_of_scope)

    done = [e for e in per_lead if e["result"] == "written"]
    remaining_new = [lead["id"] for lead in after if lead["status"] == STATUS_NEW]
    counts = {
        "found": len(found),
        "written": len(written),
        "already_processed": len(already),
        "failed": len(failed),
    }
    return {
        "found_ids": found,
        "written_ids": written,
        "already_processed_ids": already,
        "failed": failed,
        "counts": counts,
        "counts_consistent": counts["found"]
        == counts["written"] + counts["already_processed"] + counts["failed"],
        "remaining_new_ids": remaining_new,
        "arrived_during_run_ids": arrived,
        "by_category": dict(Counter(e["category"] for e in done)),
        "by_priority": dict(Counter(e["priority"] for e in done)),
        "file_status_counts": dict(Counter(lead["status"] for lead in after)),
        "leads": per_lead,
        "integrity_violations": integrity,
        "report_mismatches": mismatches,
        "warnings": warnings,
        "model_report_available": report is not None,
    }


def run_status(reconciliation: dict[str, Any], agent_error: str | None) -> str:
    """Итоговый статус прогона: ok, ok_with_warnings, incomplete или failed."""
    counts = reconciliation["counts"]
    nothing_done = counts["written"] == 0 and counts["already_processed"] == 0
    if agent_error and nothing_done:
        return "failed"  # рантайм или модель не отработали вовсе
    if reconciliation["integrity_violations"] or counts["failed"]:
        return "incomplete"
    if agent_error or reconciliation["report_mismatches"] or reconciliation["warnings"]:
        return "ok_with_warnings"
    return "ok"
