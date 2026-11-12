"""Фоновый обработчик: выполнение задачи, восстановление после остановки, повторы."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from lead_assistant.agent import AgentBackend
from lead_assistant.storage import Lead, LeadStore
from lead_assistant.web import jobs
from lead_assistant.web.db import connect, init_db
from lead_assistant.web.leads import all_views
from lead_assistant.web.worker import execute_job, run_forever
from tests.helpers import Decision, ScriptedBackend, simple_decision
from tests.web_helpers import make_paths

DRAFT = "Здравствуйте! Получили обращение."


def factory(backend: AgentBackend) -> Callable[[Path, Callable[[str], None]], Any]:
    @contextmanager
    def make(_log: Path, _echo: Callable[[str], None]) -> Iterator[AgentBackend]:
        yield backend

    return make


def queued(paths: Any) -> dict[str, Any]:
    init_db(paths.db_file)
    conn = connect(paths.db_file)
    jobs.create_job(conn, None, {"today": "2026-11-11"})
    job = jobs.claim_next(conn)
    conn.close()
    assert job is not None
    return job


def test_job_processes_new_leads_and_stores_versions(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    paths.ensure()
    job = queued(paths)
    state = execute_job(paths, job, factory(ScriptedBackend()), heartbeat_seconds=0.2)
    assert state == "done"
    conn = connect(paths.db_file)
    stored = jobs.get_job(conn, job["id"])
    assert stored is not None
    assert stored["progress"]["done"] == stored["progress"]["total"] == 14
    assert stored["summary"]["counts"]["written"] == 14 and stored["run_ids"]
    views = all_views(conn, LeadStore(paths.leads_file))
    conn.close()
    pending = [v for v in views if v.state == "pending"]
    assert len(pending) == 15
    spam = next(v for v in views if v.lead["id"] == 3)
    assert spam.result is not None and spam.result["analysis"]["uncertain"] is True
    assert spam.result["run_id"] == stored["run_ids"][0]


def test_one_failed_lead_does_not_stop_others_and_can_be_retried(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    paths.ensure()

    def skip_seven(lead: Lead) -> Decision | None:
        return None if lead["id"] == 7 else simple_decision(lead)

    job = queued(paths)
    assert execute_job(paths, job, factory(ScriptedBackend(skip_seven)), 0.2) == "done"
    conn = connect(paths.db_file)
    stored = jobs.get_job(conn, job["id"])
    assert stored is not None and stored["progress"]["pending_ids"] == [7]
    conn.close()
    retry = queued(paths)
    assert execute_job(paths, retry, factory(ScriptedBackend()), 0.2) == "done"
    assert LeadStore(paths.leads_file).get_lead(7)["status"] == "processed"


def test_worker_stopped_mid_job_is_recovered_without_rewriting(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    paths.ensure()
    job = queued(paths)
    # Обработчик успел записать часть заявок и остановился (heartbeat давно не обновлялся).
    store = LeadStore(paths.leads_file)
    for lead_id in (1, 2):
        store.update_lead(
            lead_id, "question", "medium", "processed", "Здравствуйте! Получили обращение."
        )
    conn = connect(paths.db_file)
    old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    conn.execute("UPDATE jobs SET heartbeat_at = ? WHERE id = ?", (old, job["id"]))
    assert jobs.recover_stale(conn) == [job["id"]]
    again = jobs.claim_next(conn)
    conn.close()
    assert again is not None and again["id"] == job["id"] and again["attempts"] == 2
    backend = ScriptedBackend()
    assert execute_job(paths, again, factory(backend), 0.2) == "done"
    leads = {lead["id"]: lead for lead in LeadStore(paths.leads_file).snapshot().leads}
    assert leads[1]["draft_reply"] == DRAFT  # не перезаписана
    assert all(lead["status"] == "processed" for lead in leads.values())


def test_attempts_are_limited(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    paths.ensure()
    job = queued(paths)
    conn = connect(paths.db_file)
    for _ in range(2):
        assert jobs.requeue(conn, job["id"], {"code": "LLM_UNAVAILABLE"})
        assert jobs.claim_next(conn) is not None
    assert not jobs.requeue(conn, job["id"], {"code": "LLM_UNAVAILABLE"})
    final = jobs.get_job(conn, job["id"])
    conn.close()
    assert final is not None and final["state"] == "failed" and final["error"]["attempts"] == 3


def test_run_forever_once_handles_queue_and_empty_queue(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    paths.ensure()
    leads = json.loads(paths.leads_file.read_text(encoding="utf-8"))
    for lead in leads:
        lead["status"] = "processed"
        lead.update({"category": "spam", "priority": "low", "draft_reply": None})
    paths.leads_file.write_text(json.dumps(leads, ensure_ascii=False), encoding="utf-8")
    init_db(paths.db_file)
    conn = connect(paths.db_file)
    created = jobs.create_job(conn, None)
    conn.close()
    run_forever(paths, poll_seconds=0.1, once=True)
    conn = connect(paths.db_file)
    job = jobs.get_job(conn, created["id"])
    conn.close()
    assert job is not None and job["state"] == "done"
    assert job["summary"]["text"] == "Новых заявок нет."
