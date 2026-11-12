"""Показатели качества для руководителя и выгрузка исправлений в набор для оценки."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Any

from lead_assistant.web.db import utc_now


def _latest_decisions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT d.*, r.category AS ai_category, r.priority AS ai_priority, "
        "r.draft_reply AS ai_draft, r.version AS result_version, r.run_id "
        "FROM decisions d JOIN results r ON r.id = d.result_id "
        "WHERE d.id IN (SELECT MAX(id) FROM decisions GROUP BY result_id)"
    ).fetchall()


def metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = _latest_decisions(conn)
    actions = Counter(row["action"] for row in rows)
    total = len(rows)
    category_fixes: Counter[str] = Counter()
    priority_fixes: Counter[str] = Counter()
    edited_fields: Counter[str] = Counter()
    for row in rows:
        if row["action"] != "correct":
            continue
        changes = json.loads(row["changes"] or "{}")
        for field in changes:
            edited_fields[field] += 1
        if "category" in changes:
            category_fixes[f"{row['ai_category']} → {row['category']}"] += 1
        if "priority" in changes:
            priority_fixes[f"{row['ai_priority']} → {row['priority']}"] += 1
    reasons = Counter(
        (row["reason"] or "без причины").strip().lower()
        for row in rows
        if row["action"] == "reject"
    )
    processed = conn.execute("SELECT COUNT(DISTINCT lead_key) FROM results").fetchone()[0]
    repeated = [
        {"error": key, "count": count}
        for key, count in (category_fixes + priority_fixes + reasons).most_common()
        if count > 1
    ]
    return {
        "decided": total,
        "processed_leads": processed,
        "awaiting_decision": max(processed - len({row["lead_key"] for row in rows}), 0),
        "accepted_without_edits": actions.get("accept", 0),
        "corrected": actions.get("correct", 0),
        "rejected": actions.get("reject", 0),
        "accepted_share": round(actions.get("accept", 0) / total, 3) if total else None,
        "category_corrections": [
            {"change": k, "count": v} for k, v in category_fixes.most_common()
        ],
        "priority_corrections": [
            {"change": k, "count": v} for k, v in priority_fixes.most_common()
        ],
        "edited_fields": dict(edited_fields),
        "rejection_reasons": [{"reason": k, "count": v} for k, v in reasons.most_common()],
        "repeated_errors": repeated,
    }


def corrections_as_cases(conn: sqlite3.Connection, leads: dict[str, Any]) -> dict[str, Any]:
    """Исправления менеджера → кандидаты в набор для оценки следующей версии правил.

    Формат совпадает с ``evals/cases.json``: заявка и ожидание (категория, приоритет).
    Кандидатов проверяет человек перед добавлением в зафиксированный набор.
    """
    cases = []
    for row in _latest_decisions(conn):
        changes = json.loads(row["changes"] or "{}")
        if row["action"] != "correct" or not ({"category", "priority"} & set(changes)):
            continue
        lead = leads.get(row["lead_key"])
        if lead is None:
            continue
        cases.append(
            {
                "id": f"manager-{row['id']}",
                "tags": ["from_manager_correction"],
                "lead": {k: lead.get(k) for k in ("date", "channel", "name", "contact", "text")},
                "expect": {"category": row["category"], "priority": row["priority"]},
                "agent_result": {
                    "category": row["ai_category"],
                    "priority": row["ai_priority"],
                    "run_id": row["run_id"],
                },
            }
        )
    return {"exported_at": utc_now(), "note": "кандидаты в набор для оценки", "cases": cases}
