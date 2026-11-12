"""Заявки для рабочего места: версии результата, решения менеджера, очередь проверки.

Результат AI-обработки читается из ``leads.json`` (источник истины). Каждое новое
содержимое результата (категория, приоритет, черновик) получает номер версии в SQLite
вместе с разбором прогона. Решение менеджера ссылается на конкретную версию: если
результат изменился, прежнее решение к нему не относится.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from lead_assistant.extract import FIELD_TITLES, extract, missing_for
from lead_assistant.models import STATUS_PROCESSED, LeadError, LeadId
from lead_assistant.service import validate_correction
from lead_assistant.storage import Lead, LeadStore
from lead_assistant.web.auth import User
from lead_assistant.web.db import audit, get_settings, lead_key, transaction, utc_now
from lead_assistant.web.review import default_assignee, due_at, review_reasons

ACTIONS = ("accept", "correct", "reject")
STATE_TITLES = {
    "new": "Ждёт обработки агентом",
    "pending": "Ждёт решения менеджера",
    "accepted": "Принято",
    "corrected": "Исправлено и принято",
    "rejected": "Отклонено",
}


class DecisionError(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def content_hash(category: object, priority: object, draft: object) -> str:
    payload = json.dumps([category, priority, draft], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sync_results(
    conn: sqlite3.Connection,
    leads: list[Lead],
    run_id: str | None = None,
    analyses: dict[str, dict[str, Any]] | None = None,
) -> int:
    """Заносит в SQLite новые версии результата из файла. Возвращает число новых версий."""
    added = 0
    with transaction(conn):
        for lead in leads:
            if lead.get("status") != STATUS_PROCESSED:
                continue
            key = lead_key(lead["id"])
            digest = content_hash(
                lead.get("category"), lead.get("priority"), lead.get("draft_reply")
            )
            existing = conn.execute(
                "SELECT id, analysis FROM results WHERE lead_key = ? AND content_hash = ?",
                (key, digest),
            ).fetchone()
            analysis = (analyses or {}).get(key)
            if existing is not None:
                # Разбор прогона может прийти позже снимка файла: дополняем, не создавая версию.
                if analysis and existing["analysis"] in ("{}", ""):
                    conn.execute(
                        "UPDATE results SET analysis = ?, run_id = COALESCE(run_id, ?) "
                        "WHERE id = ?",
                        (json.dumps(analysis, ensure_ascii=False), run_id, existing["id"]),
                    )
                continue
            version = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM results WHERE lead_key = ?", (key,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO results(lead_key, version, content_hash, category, priority, "
                "draft_reply, analysis, run_id, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    version,
                    digest,
                    lead.get("category"),
                    lead.get("priority"),
                    lead.get("draft_reply"),
                    json.dumps(analysis or {}, ensure_ascii=False),
                    run_id,
                    "agent" if run_id else "file",
                    utc_now(),
                ),
            )
            added += 1
    return added


def analyses_from_run(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = (run.get("reconciliation") or {}).get("leads") or []
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        result[lead_key(entry["id"])] = {
            key: entry.get(key)
            for key in ("uncertain", "manager_check", "urgency_basis", "next_action", "repeat_of")
            if entry.get(key) is not None
        }
    return result


@dataclass
class LeadView:
    lead: Lead
    result: dict[str, Any] | None
    decision: dict[str, Any] | None
    extraction: dict[str, Any]
    reasons: list[dict[str, str]]
    assignment: dict[str, Any]
    state: str

    def summary(self) -> dict[str, Any]:
        lead = self.lead
        return {
            "id": lead["id"],
            "key": lead_key(lead["id"]),
            "date": lead.get("date"),
            "channel": lead.get("channel"),
            "source": source_of(lead),
            "name": lead.get("name"),
            "text": lead.get("text"),
            "status": lead.get("status"),
            "category": lead.get("category"),
            "priority": lead.get("priority"),
            "state": self.state,
            "state_title": STATE_TITLES[self.state],
            "needs_review": bool(self.reasons) and self.state in ("pending",),
            "review_reasons": self.reasons,
            "assignee": self.assignment.get("assignee"),
            "due_at": self.assignment.get("due_at"),
            "overdue": _overdue(self.assignment.get("due_at"), self.state),
            "result_version": (self.result or {}).get("version"),
        }

    def detail(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            **self.summary(),
            "lead": self.lead,
            "result": self.result,
            "decision": self.decision,
            "extraction": self.extraction,
            "field_titles": FIELD_TITLES,
            "history": history,
        }


def _overdue(due: str | None, state: str) -> bool:
    if not due or state not in ("new", "pending"):
        return False
    return datetime.fromisoformat(due) < datetime.now(UTC)


def _result_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "version": row["version"],
        "category": row["category"],
        "priority": row["priority"],
        "draft_reply": row["draft_reply"],
        "analysis": json.loads(row["analysis"] or "{}"),
        "run_id": row["run_id"],
        "source": row["source"],
        "created_at": row["created_at"],
    }


def _decision_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "result_id": row["result_id"],
        "action": row["action"],
        "category": row["category"],
        "priority": row["priority"],
        "draft_reply": row["draft_reply"],
        "reason": row["reason"],
        "changes": json.loads(row["changes"] or "{}"),
        "previous_decision_id": row["previous_decision_id"],
        "user": row["user_name"],
        "created_at": row["created_at"],
    }


def _received(lead: Lead) -> datetime:
    value = str(lead.get("date") or "")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def build_view(conn: sqlite3.Connection, lead: Lead, settings: dict[str, Any]) -> LeadView:
    key = lead_key(lead["id"])
    result: dict[str, Any] | None = None
    if lead.get("status") == STATUS_PROCESSED:
        digest = content_hash(lead.get("category"), lead.get("priority"), lead.get("draft_reply"))
        result = _result_row(
            conn.execute(
                "SELECT * FROM results WHERE lead_key = ? AND content_hash = ?", (key, digest)
            ).fetchone()
        )
    decision = None
    if result is not None:
        decision = _decision_row(
            conn.execute(
                "SELECT d.*, u.name AS user_name FROM decisions d JOIN users u ON u.id = d.user_id "
                "WHERE d.lead_key = ? AND d.result_id = ? ORDER BY d.id DESC LIMIT 1",
                (key, result["id"]),
            ).fetchone()
        )
    base = _received(lead).date()
    found = extract(lead, base if isinstance(base, date) else None)
    extraction = found.to_dict()
    extraction["missing"] = missing_for(lead.get("category"), found, lead)
    analysis = (result or {}).get("analysis") or {}
    reasons = (
        review_reasons(
            lead.get("category"),
            lead.get("priority"),
            lead.get("draft_reply"),
            analysis,
            extraction,
        )
        if result is not None
        else []
    )
    if lead.get("status") != STATUS_PROCESSED:
        state = "new"
    elif decision is None:
        state = "pending"
    else:
        state = {"accept": "accepted", "correct": "corrected", "reject": "rejected"}[
            decision["action"]
        ]
    row = conn.execute("SELECT * FROM assignments WHERE lead_key = ?", (key,)).fetchone()
    if row is not None:
        assignment = {"assignee": row["assignee"], "due_at": row["due_at"], "manual": True}
    else:
        due = due_at(_received(lead), lead.get("priority"), settings)
        assignment = {
            "assignee": default_assignee(lead.get("category"), settings),
            "due_at": due.astimezone(UTC).isoformat() if due else None,
            "manual": False,
        }
    return LeadView(lead, result, decision, extraction, reasons, assignment, state)


def all_views(conn: sqlite3.Connection, store: LeadStore) -> list[LeadView]:
    leads = store.snapshot().leads
    sync_results(conn, leads)
    settings = get_settings(conn)
    return [build_view(conn, lead, settings) for lead in leads]


CHANNEL_TITLES = {"email": "Почта", "telegram": "Telegram"}


def source_of(lead: Lead) -> str:
    """Вкладка источника: ящик, в который пришло письмо, иначе канал заявки."""
    inbox = lead.get("inbox")
    if isinstance(inbox, str) and inbox.strip():
        return inbox.strip().lower()
    return str(lead.get("channel") or "other")


def source_tabs(views: list[LeadView]) -> list[dict[str, Any]]:
    """Вкладки «по ящикам и каналам» со счётчиками: сначала почтовые ящики, затем каналы."""
    counts: dict[str, int] = {}
    pending: dict[str, int] = {}
    for view in views:
        key = source_of(view.lead)
        counts[key] = counts.get(key, 0) + 1
        pending[key] = pending.get(key, 0) + (view.state in ("new", "pending"))
    tabs = [
        {
            "key": key,
            "title": CHANNEL_TITLES.get(key, key),
            "mailbox": "@" in key and not key.startswith("@"),
            "count": count,
            "open": pending[key],
        }
        for key, count in counts.items()
    ]
    return sorted(tabs, key=lambda tab: (not tab["mailbox"], tab["title"].lower()))


def newest_first(views: list[LeadView]) -> list[LeadView]:
    """Как в почте: сверху новые. По дате обращения, при равной — позже добавленная выше."""
    order = list(enumerate(views))
    order.sort(key=lambda item: (str(item[1].lead.get("date") or ""), item[0]), reverse=True)
    return [view for _, view in order]


def filter_views(views: list[LeadView], query: dict[str, str]) -> list[LeadView]:
    text = (query.get("q") or "").strip().lower()
    source = (query.get("source") or "").strip().lower()
    out = []
    for view in views:
        lead = view.lead
        if source and source_of(lead) != source:
            continue
        if text:
            haystack = " ".join(
                str(lead.get(k) or "")
                for k in ("id", "name", "contact", "text", "draft_reply", "channel")
            ).lower()
            if text not in haystack:
                continue
        if query.get("category") and lead.get("category") != query["category"]:
            continue
        if query.get("priority") and lead.get("priority") != query["priority"]:
            continue
        if query.get("state") and view.state != query["state"]:
            continue
        if query.get("review") == "1" and not view.summary()["needs_review"]:
            continue
        if query.get("overdue") == "1" and not view.summary()["overdue"]:
            continue
        out.append(view)
    return out


def find_view(conn: sqlite3.Connection, store: LeadStore, key: str) -> LeadView:
    try:
        lead_id: LeadId = json.loads(key)
    except json.JSONDecodeError as error:
        raise DecisionError("NOT_FOUND", "Неверный идентификатор заявки") from error
    try:
        lead = store.get_lead(lead_id)
    except LeadError as error:
        raise DecisionError("NOT_FOUND", error.message) from error
    sync_results(conn, [lead])
    return build_view(conn, lead, get_settings(conn))


def history(conn: sqlite3.Connection, key: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in conn.execute(
        "SELECT * FROM results WHERE lead_key = ? ORDER BY version", (key,)
    ).fetchall():
        events.append({"type": "result", "at": row["created_at"], **(_result_row(row) or {})})
    for row in conn.execute(
        "SELECT d.*, u.name AS user_name FROM decisions d JOIN users u ON u.id = d.user_id "
        "WHERE d.lead_key = ? ORDER BY d.id",
        (key,),
    ).fetchall():
        version = conn.execute(
            "SELECT version FROM results WHERE id = ?", (row["result_id"],)
        ).fetchone()
        events.append(
            {
                "type": "decision",
                "at": row["created_at"],
                "result_version": version[0] if version else None,
                **(_decision_row(row) or {}),
            }
        )
    events.sort(key=lambda event: (event["at"], event["type"] == "decision"))
    return events


def decide(
    conn: sqlite3.Connection,
    store: LeadStore,
    key: str,
    user: User,
    action: str,
    result_version: object,
    category: object = None,
    priority: object = None,
    draft_reply: object = None,
    reason: object = None,
) -> dict[str, Any]:
    """Решение менеджера по конкретной версии результата."""
    if action not in ACTIONS:
        raise DecisionError("INVALID_ARGUMENT", f"Неизвестное действие: {action}")
    view = find_view(conn, store, key)
    if view.result is None:
        raise DecisionError("NOT_PROCESSED", "Заявка ещё не обработана агентом")
    if result_version != view.result["version"]:
        raise DecisionError(
            "CONFLICT",
            "Результат обработки изменился, пока вы его смотрели. Обновите карточку.",
            current_version=view.result["version"],
        )
    previous = view.decision
    base = previous if previous and previous["action"] != "reject" else view.result
    values = {
        "category": base["category"],
        "priority": base["priority"],
        "draft_reply": base["draft_reply"],
    }
    warnings: list[str] = []
    reason_text = str(reason).strip() if isinstance(reason, str) else ""
    if action == "correct":
        correction = validate_correction(view.lead, category, priority, draft_reply)
        values = {
            "category": correction.category,
            "priority": correction.priority,
            "draft_reply": correction.draft_reply,
        }
        warnings = correction.warnings
    if action == "reject" and not reason_text:
        raise DecisionError("INVALID_ARGUMENT", "Укажите причину отклонения")
    changes = {
        field: {"from": base[field], "to": values[field]}
        for field in values
        if base[field] != values[field]
    }
    if action == "correct" and not changes:
        raise DecisionError("INVALID_ARGUMENT", "Исправление не меняет ни одного поля")
    if previous and previous["action"] == action and action == "accept":
        raise DecisionError("DUPLICATE", "Эта версия уже принята")
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO decisions(lead_key, result_id, action, category, priority, draft_reply, "
            "reason, changes, previous_decision_id, user_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                view.result["id"],
                action,
                values["category"],
                values["priority"],
                values["draft_reply"],
                reason_text or None,
                json.dumps(changes, ensure_ascii=False),
                previous["id"] if previous else None,
                user.id,
                utc_now(),
            ),
        )
        audit(
            conn,
            f"decision_{action}",
            user.id,
            f"lead:{key}",
            result_version=view.result["version"],
            changes=list(changes),
            reason=reason_text or None,
        )
    return {"decision_id": cursor.lastrowid, "warnings": warnings}


def assign(conn: sqlite3.Connection, key: str, user: User, assignee: object, due: object) -> None:
    if assignee is not None and not isinstance(assignee, str):
        raise DecisionError("INVALID_ARGUMENT", "Ответственный должен быть строкой")
    due_text = None
    if due:
        try:
            due_text = datetime.fromisoformat(str(due)).astimezone(UTC).isoformat()
        except ValueError as error:
            raise DecisionError("INVALID_ARGUMENT", "Срок реакции — дата и время ISO") from error
    with transaction(conn):
        conn.execute(
            "INSERT INTO assignments(lead_key, assignee, due_at, set_by, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(lead_key) DO UPDATE SET "
            "assignee = excluded.assignee, "
            "due_at = excluded.due_at, set_by = excluded.set_by, updated_at = excluded.updated_at",
            (key, (assignee or "").strip() or None, due_text, user.id, utc_now()),
        )
        audit(conn, "assigned", user.id, f"lead:{key}", assignee=assignee, due_at=due_text)
