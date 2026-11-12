"""Несколько почтовых ящиков и фоновая проверка почты."""

from __future__ import annotations

from pathlib import Path

from lead_assistant.storage import LeadStore
from lead_assistant.web import connectors, jobs, mockservice, worker
from lead_assistant.web.api import create_app
from lead_assistant.web.db import connect
from tests.web_helpers import PROCESSED, client_for, error_code, make_paths


def test_admin_adds_configures_and_removes_extra_mailboxes(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, PROCESSED)
    with client_for(paths, "admin") as admin:
        first = admin.post("/api/connectors")
        second = admin.post("/api/connectors")
        assert first.status_code == 201 and first.json()["name"] == "email-2"
        assert second.json()["name"] == "email-3" and second.json()["removable"] is True
        names = [c["name"] for c in admin.get("/api/connectors").json()["connectors"]]
        assert names[:3] == ["email", "email-2", "email-3"], "ящики идут первыми, по порядку"
        saved = admin.put("/api/connectors/email-2", json={"host": "imap.x", "user": "Sales@X.ru"})
        assert saved.json()["title"] == "Почта: Sales@X.ru"
        assert admin.delete("/api/connectors/email-3").status_code == 200
        main = admin.delete("/api/connectors/email")
        assert main.status_code == 409 and error_code(main) == "NOT_REMOVABLE"
        names = [c["name"] for c in admin.get("/api/connectors").json()["connectors"]]
        assert "email-3" not in names and "email" in names
    with client_for(paths, "manager") as manager:
        assert manager.post("/api/connectors").status_code == 403


def test_background_check_imports_new_messages_and_queues_processing(tmp_path: Path) -> None:
    server, base = mockservice.start()
    paths = make_paths(tmp_path, PROCESSED)
    create_app(paths)  # база и администратор
    conn = connect(paths.db_file)
    try:
        connectors.configure(
            conn, "telegram", {"bot_token": mockservice.TOKEN, "api_base": base}, 1
        )
        connectors.check(conn, "telegram", 1)
        assert worker.check_mail(paths, conn) == 1
        active = jobs.active_job(conn)
        assert active is not None and active["params"] == {"source": "mail_check"}
        # Повторная проверка: дублей нет, вторая задача не ставится.
        assert worker.check_mail(paths, conn) == 0
        assert jobs.active_job(conn)["id"] == active["id"]  # type: ignore[index]
    finally:
        conn.close()
        server.shutdown()
    leads = LeadStore(paths.leads_file).snapshot().leads
    assert sum(lead.get("source_id") == "telegram:9001" for lead in leads) == 1
