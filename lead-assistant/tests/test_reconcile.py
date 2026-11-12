from __future__ import annotations

import copy
from typing import Any

from lead_assistant.agent import ToolCall
from lead_assistant.reconcile import (
    check_integrity,
    check_processed_shape,
    parse_model_report,
    reconcile,
    run_status,
)
from lead_assistant.storage import Lead, parse_leads
from tests.helpers import ORIGINAL


def original() -> list[Lead]:
    return parse_leads(ORIGINAL.read_bytes())


def processed(lead: Lead, category: str = "question", priority: str = "medium") -> None:
    lead.update(status="processed", category=category, priority=priority, draft_reply="Ответ")


def update_call(lead_id: Any, ok: bool | None, result: str | None = None, **extra: Any) -> ToolCall:
    args = {"category": "question", "priority": "medium", **extra.pop("args", {})}
    return ToolCall(
        seq=1, tool_use_id="t", tool="update_lead", lead_id=lead_id, args=args,
        started=0.0, ok=ok, result=result, **extra,
    )  # fmt: skip


def test_integrity_detects_every_kind_of_damage() -> None:
    before = original()
    scope = [lead["id"] for lead in before if lead["status"] == "new"]
    assert check_integrity(before, copy.deepcopy(before), scope) == []

    reordered = copy.deepcopy(before)
    reordered[0], reordered[1] = reordered[1], reordered[0]
    assert "ORDER_OR_IDS_CHANGED" in check_integrity(before, reordered, scope)

    shorter = copy.deepcopy(before)[:-1]
    problems = check_integrity(before, shorter, scope)
    assert "COUNT_CHANGED: 15 -> 14" in problems and "LEAD_MISSING: 15" in problems

    edited = copy.deepcopy(before)
    edited[3]["contact"] = "@anna"  # поле вне разрешённого набора
    assert check_integrity(before, edited, scope) == ["IMMUTABLE_FIELDS_CHANGED: 4"]

    dropped = copy.deepcopy(before)
    del dropped[3]["channel"]
    assert "IMMUTABLE_FIELDS_CHANGED: 4" in check_integrity(before, dropped, scope)

    touched = copy.deepcopy(before)
    touched[14]["draft_reply"] = "Переписано"  # ранее обработанная заявка
    assert check_integrity(before, touched, scope) == ["OUT_OF_SCOPE_LEAD_CHANGED: 15"]

    retyped = copy.deepcopy(before)
    retyped[0]["id"] = "1"
    assert "ORDER_OR_IDS_CHANGED" in check_integrity(before, retyped, scope)


def test_processed_shape() -> None:
    assert (
        check_processed_shape({"id": 1, "category": "spam", "priority": "low", "draft_reply": None})
        == []
    )
    assert check_processed_shape(
        {"id": 1, "category": "sale", "priority": "low", "draft_reply": ""}
    ) == ["EMPTY_DRAFT: 1"]
    assert check_processed_shape(
        {"id": 1, "category": "vip", "priority": "top", "draft_reply": "x"}
    ) == [
        "INVALID_CATEGORY: 1",
        "INVALID_PRIORITY: 1",
    ]
    assert check_processed_shape(
        {"id": 1, "category": "spam", "priority": "low", "draft_reply": "x"}
    ) == ["SPAM_WITH_DRAFT: 1"]
    assert check_processed_shape({"id": 1, "category": "sale", "priority": "low"}) == [
        "DRAFT_FIELD_MISSING: 1"
    ]
    assert check_processed_shape({"id": 1, "category": "spam", "priority": "low"}) == [
        "DRAFT_FIELD_MISSING: 1"
    ]


def test_parse_model_report() -> None:
    text = 'Сводка.\n```json\n{"leads": []}\n```\nтекст\n```json\n{"leads": [{"id": 1}]}\n```'
    report, error = parse_model_report(text)
    assert error is None and report == {"int:1": {"id": 1}}  # берётся последний блок
    assert parse_model_report("без блока") == (None, "REPORT_MISSING")
    assert parse_model_report("```json\n{oops}\n```") == (None, "REPORT_INVALID_JSON")
    assert parse_model_report('```json\n{"leads": {}}\n```') == (None, "REPORT_INVALID_SHAPE")
    assert parse_model_report('```json\n{"leads": [{"id": true}]}\n```') == (
        None,
        "REPORT_INVALID_SHAPE",
    )


def test_every_found_lead_lands_in_exactly_one_group() -> None:
    before = original()
    after = copy.deepcopy(before)
    processed(after[0])  # 1: подтверждено инструментом
    processed(after[1])  # 2: обработал кто-то другой, наш вызов получил CONFLICT
    processed(after[2])  # 3: обработана, а вызовов от нас не было
    calls = [
        update_call(1, True, "updated"),
        update_call(2, False, code="CONFLICT"),
        update_call(4, False, code="INVALID_ARGUMENT"),
        update_call(5, False, code="LOCK_TIMEOUT"),
    ]
    rec = reconcile(before, after, calls, "")

    assert rec["written_ids"] == [1]
    assert rec["already_processed_ids"] == [2, 3]
    failed = {item["id"]: item["reason"] for item in rec["failed"]}
    assert (
        failed[4] == "INVALID_ARGUMENT" and failed[5] == "LOCK_TIMEOUT" and failed[6] == "NOT_READ"
    )
    assert rec["counts"] == {"found": 14, "written": 1, "already_processed": 2, "failed": 11}
    assert rec["counts_consistent"]
    grouped = rec["written_ids"] + rec["already_processed_ids"] + [f["id"] for f in rec["failed"]]
    assert sorted(grouped) == rec["found_ids"]  # без пропусков и повторов
    assert rec["warnings"] == ["REPORT_MISSING", "WRITTEN_WITHOUT_READ: 1"]


def test_tool_confirmation_without_file_change_is_an_integrity_violation() -> None:
    before = original()
    rec = reconcile(before, copy.deepcopy(before), [update_call(1, True, "updated")], "")
    assert "FALSE_CONFIRMATION: 1" in rec["integrity_violations"]
    assert rec["counts"]["written"] == 0
    assert run_status(rec, None) == "incomplete"


def test_lock_timeout_is_not_counted_as_our_write() -> None:
    before = original()
    after = copy.deepcopy(before)
    processed(after[0])
    rec = reconcile(before, after, [update_call(1, False, code="LOCK_TIMEOUT")], "")
    assert rec["already_processed_ids"] == [1] and rec["written_ids"] == []


def test_update_outside_run_set_is_flagged() -> None:
    before = original()
    rec = reconcile(before, copy.deepcopy(before), [update_call(15, False, code="CONFLICT")], "")
    assert "UPDATE_OUTSIDE_RUN_SET: 15" in rec["warnings"]


def test_high_priority_requires_basis_in_report() -> None:
    before = original()
    after = copy.deepcopy(before)
    processed(after[6], "sale", "high")
    report = (
        '```json\n{"leads": [{"id": 7, "category": "sale", "priority": "high", '
        '"result": "written", "uncertain": false}]}\n```'
    )
    call = update_call(7, True, "updated", args={"category": "sale", "priority": "high"})
    rec = reconcile(before, after, [call], report)
    assert "HIGH_WITHOUT_BASIS: 7" in rec["warnings"]
    assert rec["by_priority"] == {"high": 1}


def test_run_status_matrix() -> None:
    def rec(written: int = 0, failed: int = 0, **extra: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "counts": {
                "found": written + failed,
                "written": written,
                "already_processed": 0,
                "failed": failed,
            },
            "integrity_violations": [],
            "report_mismatches": [],
            "warnings": [],
        }
        return {**base, **extra}

    assert run_status(rec(written=3), None) == "ok"
    assert run_status(rec(), None) == "ok"  # повторный прогон: ноль новых
    assert run_status(rec(written=3, warnings=["X"]), None) == "ok_with_warnings"
    assert run_status(rec(written=2, failed=1), None) == "incomplete"
    assert run_status(rec(written=3, integrity_violations=["X"]), None) == "incomplete"
    assert run_status(rec(failed=3), "AUTH_FAILED") == "failed"
    assert run_status(rec(), "AUTH_FAILED") == "failed"
    assert run_status(rec(written=3), "MAX_TURNS") == "ok_with_warnings"


def test_leads_added_during_run_are_not_a_violation() -> None:
    before = original()
    after = copy.deepcopy(before)
    after.append({"id": 16, "text": "пришла во время прогона", "status": "new"})
    scope = [lead["id"] for lead in before if lead["status"] == "new"]
    assert check_integrity(before, after, scope) != []  # строгая сверка с оригиналом
    assert check_integrity(before, after, scope, allow_additions=True) == []

    rec = reconcile(before, after, [], "", model_invoked=False)
    assert rec["integrity_violations"] == []
    assert rec["arrived_during_run_ids"] == [16] and 16 in rec["remaining_new_ids"]
    assert rec["counts"]["found"] == 14  # новая заявка ждёт следующего прогона
    assert rec["warnings"] == ["NEW_LEADS_ARRIVED_DURING_RUN: [16]"]


def test_lead_added_after_snapshot_but_processed_by_model_is_counted() -> None:
    before = original()
    after = copy.deepcopy(before)
    after.append({"id": 16, "text": "успела попасть в list_leads", "status": "new"})
    processed(after[15])
    rec = reconcile(before, after, [update_call(16, True, "updated")], "", model_invoked=False)
    assert 16 in rec["found_ids"] and rec["written_ids"] == [16]
    assert rec["counts"]["found"] == 15 and rec["counts_consistent"]
    assert "UPDATE_OUTSIDE_RUN_SET: 16" not in rec["warnings"]
    assert rec["integrity_violations"] == []


def test_removed_lead_is_always_a_violation() -> None:
    before = original()
    after = copy.deepcopy(before)[1:]
    rec = reconcile(before, after, [], "", model_invoked=False)
    assert "LEAD_MISSING: 1" in rec["integrity_violations"]
    assert {"id": 1, "reason": "UNEXPECTED_STATUS:missing"} in rec["failed"]


def test_summary_lists_spam_for_a_quick_look() -> None:
    from lead_assistant.report import render_summary

    before = original()
    after = copy.deepcopy(before)
    after[2].update(status="processed", category="spam", priority="low", draft_reply=None)
    call = update_call(3, True, "updated", args={"category": "spam", "priority": "low"})
    rec = reconcile(before, after, [call], "", model_invoked=False)
    run = {
        "run_id": "r", "today": "2026-11-11", "status": "incomplete", "error": None,
        "runtime": {"model": "m"}, "rules": {"version": "1"}, "reconciliation": rec,
    }  # fmt: skip
    summary = render_summary(run)
    assert "## Спам (без черновика)" in summary and "ID: 3." in summary


def test_summary_sentences_end_with_a_single_period() -> None:
    from lead_assistant.report import render_summary

    before = original()
    after = copy.deepcopy(before)
    processed(after[8], "complaint", "high")
    report = (
        '```json\n{"leads": [{"id": 9, "category": "complaint", "priority": "high", '
        '"result": "written", "uncertain": false, "urgency_basis": "двойное списание.", '
        '"next_action": "Проверить платежи."}]}\n```'
    )
    call = update_call(9, True, "updated", args={"category": "complaint", "priority": "high"})
    rec = reconcile(before, after, [call], report)
    run = {
        "run_id": "r", "today": "2026-11-11", "status": "incomplete", "error": None,
        "runtime": {"model": "m"}, "rules": {"version": "1"}, "reconciliation": rec,
    }  # fmt: skip
    summary = render_summary(run)
    assert "Основание: двойное списание. Действие: Проверить платежи." in summary
    assert ".." not in summary
