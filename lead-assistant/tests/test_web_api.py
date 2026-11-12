"""API рабочего места: вход, права, решения по версиям результата, задачи."""

from __future__ import annotations

import json
from pathlib import Path

from starlette.testclient import TestClient

from lead_assistant.storage import LeadStore, sha256_hex
from lead_assistant.web.api import create_app
from lead_assistant.web.db import connect
from tests.web_helpers import PROCESSED, client_for, error_code, make_paths


def test_first_start_creates_admin_who_must_change_password(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    app = create_app(paths)
    secret = paths.data_dir / "initial-admin.txt"
    assert secret.exists()
    password = secret.read_text(encoding="utf-8").split("пароль: ")[1].split("\n")[0]
    conn = connect(paths.db_file)
    stored = conn.execute("SELECT password_hash FROM users WHERE login='admin'").fetchone()[0]
    conn.close()
    assert password not in stored and stored.startswith("pbkdf2_sha256$")
    with TestClient(app) as client:
        assert (
            client.post("/api/auth/login", json={"login": "admin", "password": "x"}).status_code
            == 401
        )
        assert (
            client.post(
                "/api/auth/login", json={"login": "admin", "password": password}
            ).status_code
            == 200
        )
        blocked = client.get("/api/leads")
        assert blocked.status_code == 403 and error_code(blocked) == "PASSWORD_CHANGE_REQUIRED"
        changed = client.post(
            "/api/auth/password",
            json={"old": password, "new": "another-password-1"},
            headers={"X-Requested-With": "lead-assistant"},
        )
        assert changed.status_code == 200
        assert client.get("/api/leads").status_code == 200
    assert not secret.exists(), "файл с начальным паролем удаляется после смены"
    # Повторный запуск не создаёт второго администратора и не печатает пароль заново.
    create_app(paths)
    assert not secret.exists()


def test_requests_without_session_or_app_header_are_rejected(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, PROCESSED)
    with TestClient(create_app(paths)) as anonymous:
        assert anonymous.get("/api/leads").status_code == 401
    with client_for(paths) as client:
        response = client.post(
            "/api/leads/1/decision",
            json={"action": "accept", "result_version": 1},
            headers={"X-Requested-With": ""},
        )
        assert response.status_code == 403 and error_code(response) == "CSRF"


def test_list_filters_and_review_queue(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, PROCESSED)
    with client_for(paths) as client:
        data = client.get("/api/leads").json()
        assert data["counts"]["total"] == 15 and data["counts"]["pending"] == 15
        dates = [lead["date"] for lead in data["leads"]]
        assert dates == sorted(dates, reverse=True), "как в почте: сверху новые"
        high = client.get("/api/leads?priority=high").json()["leads"]
        assert {lead["id"] for lead in high} == {2, 7, 9, 13}
        assert all(lead["needs_review"] for lead in high)
        assert all(any(r["code"] == "urgent" for r in lead["review_reasons"]) for lead in high)
        spam = client.get("/api/leads?category=spam").json()["leads"]
        assert {lead["id"] for lead in spam} == {3, 6, 12}
        found = client.get("/api/leads?q=4630").json()["leads"]
        assert [lead["id"] for lead in found] == [9]
        review = client.get("/api/leads?review=1").json()["leads"]
        assert review and all(lead["needs_review"] for lead in review)
        complaint = next(lead for lead in data["leads"] if lead["id"] == 9)
        assert complaint["assignee"] == "Отдел претензий" and complaint["due_at"]


def test_decision_is_bound_to_result_version_and_kept_in_history(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, PROCESSED)
    before = sha256_hex(paths.leads_file.read_bytes())
    with client_for(paths) as client:
        detail = client.get("/api/leads/7").json()
        version = detail["result"]["version"]
        stale = client.post(
            "/api/leads/7/decision", json={"action": "accept", "result_version": 99}
        )
        assert stale.status_code == 409 and error_code(stale) == "CONFLICT"
        accepted = client.post(
            "/api/leads/7/decision", json={"action": "accept", "result_version": version}
        )
        assert accepted.status_code == 200 and accepted.json()["lead"]["state"] == "accepted"
        # Ответ на решение — та же полная карточка, что и при чтении (иначе интерфейс падал).
        assert set(accepted.json()["lead"]) == set(detail)
        twice = client.post(
            "/api/leads/7/decision", json={"action": "accept", "result_version": version}
        )
        assert twice.status_code == 409
        # Изменение уже согласованного черновика — новое решение со ссылкой на предыдущее.
        corrected = client.post(
            "/api/leads/7/decision",
            json={
                "action": "correct",
                "result_version": version,
                "category": "sale",
                "priority": "high",
                "draft_reply": "Здравствуйте, Марина! Менеджер подготовит предложение.",
            },
        )
        assert corrected.status_code == 200
        lead = corrected.json()["lead"]
        assert lead["state"] == "corrected"
        assert lead["decision"]["changes"]["draft_reply"]["to"].startswith("Здравствуйте, Марина")
        kinds = [(h["type"], h.get("action")) for h in lead["history"]]
        assert kinds == [("result", None), ("decision", "accept"), ("decision", "correct")]
        no_reason = client.post(
            "/api/leads/9/decision", json={"action": "reject", "result_version": 1}
        )
        assert no_reason.status_code == 400
        bad = client.post(
            "/api/leads/9/decision",
            json={
                "action": "correct",
                "result_version": 1,
                "category": "vip",
                "priority": "high",
                "draft_reply": "x",
            },
        )
        assert bad.status_code == 400
    # Решения менеджера живут в SQLite: файл заявок (источник истины агента) не меняется.
    assert sha256_hex(paths.leads_file.read_bytes()) == before


def test_new_result_version_needs_new_decision(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, PROCESSED)
    with client_for(paths) as client:
        client.post("/api/leads/8/decision", json={"action": "accept", "result_version": 1})
        data = json.loads(paths.leads_file.read_text(encoding="utf-8"))
        lead = next(item for item in data if item["id"] == 8)
        lead["draft_reply"] = "Спасибо за отзыв! Рады, что всё получили."
        paths.leads_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        detail = client.get("/api/leads/8").json()
        assert detail["result"]["version"] == 2
        assert detail["state"] == "pending" and detail["decision"] is None


def test_roles_limit_quality_settings_and_connectors(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, PROCESSED)
    with client_for(paths, "manager") as manager:
        assert manager.get("/api/quality").status_code == 403
        assert manager.put("/api/settings", json={"timezone": "UTC"}).status_code == 403
        assert manager.put("/api/connectors/tms", json={"base_url": "http://x"}).status_code == 403
        assert manager.get("/api/leads").status_code == 200
    with client_for(paths, "supervisor") as supervisor:
        client_quality = supervisor.get("/api/quality")
        assert client_quality.status_code == 200
        assert supervisor.put("/api/settings", json={"timezone": "UTC"}).status_code == 403
    with client_for(paths, "admin") as admin:
        bad = admin.put("/api/settings", json={"timezone": "Mars/Base"})
        assert bad.status_code == 400
        ok = admin.put("/api/settings", json={"sla_hours": {"high": 1, "medium": 4, "low": 16}})
        assert ok.status_code == 200 and ok.json()["demo"] is False


def test_quality_metrics_and_export_of_corrections(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, PROCESSED)
    with client_for(paths, "supervisor") as client:
        client.post("/api/leads/2/decision", json={"action": "accept", "result_version": 1})
        client.post(
            "/api/leads/14/decision",
            json={
                "action": "correct",
                "result_version": 1,
                "category": "sale",
                "priority": "high",
                "draft_reply": "Hello! Our manager will contact you.",
            },
        )
        client.post(
            "/api/leads/5/decision",
            json={"action": "reject", "result_version": 1, "reason": "Не тот тон"},
        )
        metrics = client.get("/api/quality").json()
        assert metrics["decided"] == 3 and metrics["accepted_share"] == round(1 / 3, 3)
        assert metrics["priority_corrections"] == [{"change": "medium → high", "count": 1}]
        assert metrics["rejection_reasons"] == [{"reason": "не тот тон", "count": 1}]
        cases = client.get("/api/quality/cases").json()["cases"]
        assert len(cases) == 1 and cases[0]["expect"] == {"category": "sale", "priority": "high"}


def test_second_job_is_refused_while_one_is_active(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    with client_for(paths) as client:
        first = client.post("/api/jobs", json={})
        assert first.status_code == 202
        second = client.post("/api/jobs", json={})
        assert second.status_code == 409 and error_code(second) == "ALREADY_RUNNING"
        assert (
            client.get(f"/api/jobs/{first.json()['job']['id']}").json()["job"]["state"] == "queued"
        )
        assert client.post(f"/api/jobs/{first.json()['job']['id']}/cancel").status_code == 200
        assert client.post("/api/jobs", json={}).status_code == 202


def test_health_reports_broken_leads_file(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    with client_for(paths) as client:
        assert client.get("/api/health").json()["ok"] is True
        paths.leads_file.write_text("[{broken", encoding="utf-8")
        response = client.get("/api/health")
        assert response.status_code == 503 and "STORAGE_CORRUPT" in response.json()["problems"][0]
        listing = client.get("/api/leads")
        assert listing.status_code == 503 and error_code(listing) == "STORAGE_CORRUPT"


def test_string_ids_keep_their_type(tmp_path: Path) -> None:
    source = tmp_path / "src.json"
    source.write_text(
        json.dumps(
            [
                {
                    "id": "A-1",
                    "date": "2026-11-10",
                    "channel": "email",
                    "name": "Иван",
                    "contact": "i@example.com",
                    "text": "Нужно перевезти 2 тонны из Казани в Москву",
                    "status": "new",
                },
                {
                    "id": 1,
                    "date": "2026-11-10",
                    "channel": "email",
                    "name": "Пётр",
                    "contact": "p@example.com",
                    "text": "Вопрос",
                    "status": "new",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    paths = make_paths(tmp_path, source)
    with client_for(paths) as client:
        keys = [lead["key"] for lead in client.get("/api/leads").json()["leads"]]
        assert keys == ["1", '"A-1"'], "при равной дате выше та, что добавлена позже"
        detail = client.get('/api/leads/"A-1"').json()
        assert detail["lead"]["id"] == "A-1"
        assert detail["extraction"]["fields"]["route"][0]["value"] == {
            "from": "Казани",
            "to": "Москву",
        }
        assert client.get('/api/leads/"1"').status_code == 404
    assert LeadStore(paths.leads_file).get_lead("A-1")["status"] == "new"


def test_source_tabs_split_leads_by_mailbox_and_channel(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, PROCESSED)
    store = LeadStore(paths.leads_file)
    base = {
        "date": "2026-11-12",
        "name": "Ольга",
        "text": "Нужно перевезти 2 тонны",
        "status": "new",
    }
    store.append_leads(
        [
            {**base, "channel": "email", "contact": "o@x.test", "inbox": "Sales@Mail.test"},
            {**base, "channel": "email", "contact": "p@x.test", "inbox": "sales@mail.test"},
            {**base, "channel": "telegram", "contact": "@olga"},
        ]
    )
    with client_for(paths) as client:
        data = client.get("/api/leads").json()
        tabs = {tab["key"]: tab for tab in data["sources"]}
        assert data["sources"][0]["key"] == "sales@mail.test", "почтовые ящики идут первыми"
        assert tabs["sales@mail.test"]["count"] == 2 and tabs["sales@mail.test"]["open"] == 2
        in_telegram = sum(lead["channel"] == "telegram" for lead in data["leads"])
        assert tabs["telegram"]["title"] == "Telegram" and tabs["telegram"]["count"] == in_telegram
        # Под ящиком «непрочитанные» по срочности (и ещё не разобранные) в сумме дают число ящика.
        for tab in data["sources"]:
            parts = ("high", "medium", "low", "None")
            opened = sum(
                data["folders"].get(f"open:source:{tab['key']}|priority:{p}", 0) for p in parts
            )
            assert opened == tab["open"], tab["key"]
        # Счётчики папок левой панели сходятся с фильтрами.
        assert data["folders"]["state:new"] == 3
        assert data["folders"]["category:spam"] == len(
            client.get("/api/leads?category=spam").json()["leads"]
        )
        overdue = client.get("/api/leads?overdue=1").json()["leads"]
        assert len(overdue) == data["counts"]["overdue"] and all(x["overdue"] for x in overdue)
        only_box = client.get("/api/leads?source=sales@mail.test").json()["leads"]
        assert [lead["source"] for lead in only_box] == ["sales@mail.test"] * 2
        assert len(client.get("/api/leads?source=email").json()["leads"]) == len(
            [t for t in data["leads"] if t["source"] == "email"]
        )
