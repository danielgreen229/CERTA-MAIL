"""Задачи фоновой обработки: постановка, захват обработчиком, прогресс, восстановление."""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from lead_assistant.web.db import audit, transaction, utc_now

KIND_PROCESS = "process"
STALE_AFTER_SECONDS = 90
TRANSIENT_ERRORS = ("LLM_UNAVAILABLE", "TIMEOUT", "LOCK_TIMEOUT", "STORAGE_IO", "MCP_UNAVAILABLE")


class JobError(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "kind": row["kind"],
        "state": row["state"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "heartbeat_at": row["heartbeat_at"],
        "attempts": row["attempts"],
        "max_attempts": row["max_attempts"],
        "params": json.loads(row["params"]),
        "progress": json.loads(row["progress"]),
        "run_ids": json.loads(row["run_ids"]),
        "summary": json.loads(row["summary"]) if row["summary"] else None,
        "error": json.loads(row["error"]) if row["error"] else None,
    }


def create_job(
    conn: sqlite3.Connection, user_id: int | None, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Ставит задачу обработки. Вторая активная задача не создаётся: возвращается конфликт."""
    job_id = datetime.now(UTC).strftime("job-%Y%m%dT%H%M%SZ-") + secrets.token_hex(3)
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO jobs(id, kind, state, requested_by, created_at, params) "
                "VALUES (?, ?, 'queued', ?, ?, ?)",
                (job_id, KIND_PROCESS, user_id, utc_now(), json.dumps(params or {})),
            )
            audit(conn, "job_created", user_id, f"job:{job_id}", params=params or {})
    except sqlite3.IntegrityError as error:
        active = active_job(conn)
        raise JobError(
            "ALREADY_RUNNING",
            "Обработка уже идёт — новая задача не создана",
            job_id=active["id"] if active else None,
        ) from error
    job = get_job(conn, job_id)
    assert job is not None
    return job


def get_job(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


def active_job(conn: sqlite3.Connection) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            "SELECT * FROM jobs WHERE state IN ('queued', 'running') ORDER BY created_at LIMIT 1"
        ).fetchone()
    )


def list_jobs(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
    return [job for job in (_row(row) for row in rows.fetchall()) if job is not None]


def claim_next(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Обработчик забирает задачу из очереди; атомарно, даже при нескольких обработчиках."""
    with transaction(conn):
        row = conn.execute(
            "SELECT id FROM jobs WHERE state = 'queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        now = utc_now()
        conn.execute(
            "UPDATE jobs SET state = 'running', started_at = COALESCE(started_at, ?), "
            "heartbeat_at = ?, attempts = attempts + 1 WHERE id = ? AND state = 'queued'",
            (now, now, row["id"]),
        )
    return get_job(conn, row["id"])


def heartbeat(conn: sqlite3.Connection, job_id: str, progress: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE jobs SET heartbeat_at = ?, progress = ? WHERE id = ? AND state = 'running'",
        (utc_now(), json.dumps(progress, ensure_ascii=False), job_id),
    )


def add_run(conn: sqlite3.Connection, job_id: str, run_id: str) -> None:
    with transaction(conn):
        row = conn.execute("SELECT run_ids FROM jobs WHERE id = ?", (job_id,)).fetchone()
        runs = json.loads(row["run_ids"]) if row else []
        if run_id not in runs:
            runs.append(run_id)
        conn.execute("UPDATE jobs SET run_ids = ? WHERE id = ?", (json.dumps(runs), job_id))


def finish(
    conn: sqlite3.Connection,
    job_id: str,
    state: str,
    summary: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE jobs SET state = ?, finished_at = ?, summary = ?, error = ? WHERE id = ?",
            (
                state,
                utc_now(),
                json.dumps(summary, ensure_ascii=False) if summary is not None else None,
                json.dumps(error, ensure_ascii=False) if error is not None else None,
                job_id,
            ),
        )
        audit(conn, f"job_{state}", None, f"job:{job_id}", error=(error or {}).get("code"))


def requeue(conn: sqlite3.Connection, job_id: str, error: dict[str, Any]) -> bool:
    """Повтор после временной ошибки. False — попытки исчерпаны, задача завершена ошибкой."""
    job = get_job(conn, job_id)
    if job is None:
        return False
    if job["attempts"] >= job["max_attempts"]:
        finish(conn, job_id, "failed", error={**error, "attempts": job["attempts"]})
        return False
    conn.execute(
        "UPDATE jobs SET state = 'queued', error = ? WHERE id = ?",
        (json.dumps(error, ensure_ascii=False), job_id),
    )
    return True


def recover_stale(conn: sqlite3.Connection, stale_after: float = STALE_AFTER_SECONDS) -> list[str]:
    """Задачи, чей обработчик перестал отмечаться (упал, перезапущен), возвращаются в очередь.

    Уже записанные заявки повторно не обрабатываются: прогон берёт только заявки в
    статусе new, а записанные проверяются по файлу.
    """
    border = datetime.now(UTC) - timedelta(seconds=stale_after)
    recovered: list[str] = []
    for row in conn.execute("SELECT id, heartbeat_at FROM jobs WHERE state = 'running'").fetchall():
        beat = row["heartbeat_at"]
        if (beat is None or datetime.fromisoformat(beat) < border) and requeue(
            conn, row["id"], {"code": "WORKER_LOST", "message": "обработчик остановился"}
        ):
            recovered.append(row["id"])
    return recovered


def cancel(conn: sqlite3.Connection, job_id: str, user_id: int) -> None:
    with transaction(conn):
        updated = conn.execute(
            "UPDATE jobs SET state = 'cancelled', finished_at = ? "
            "WHERE id = ? AND state = 'queued'",
            (utc_now(), job_id),
        ).rowcount
        if not updated:
            raise JobError("NOT_CANCELLABLE", "Отменить можно только задачу в очереди")
        audit(conn, "job_cancelled", user_id, f"job:{job_id}")
