"""Общие средства тестов рабочего места: приложение на временной копии и вход."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

from lead_assistant.web.api import create_app
from lead_assistant.web.auth import create_user
from lead_assistant.web.config import AppPaths
from lead_assistant.web.db import connect
from tests.helpers import ORIGINAL, PROJECT_ROOT

PROCESSED = PROJECT_ROOT.parent / "release" / "leads.processed.json"
HEADERS = {"X-Requested-With": "lead-assistant"}
PASSWORD = "test-password-123"


def make_paths(tmp_path: Path, source: Path = ORIGINAL) -> AppPaths:
    data = tmp_path / "данные с пробелами"
    data.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, data / "leads.json")
    return AppPaths(
        data_dir=data,
        leads_file=data / "leads.json",
        runs_dir=tmp_path / "runs",
        db_file=data / "app.db",
        uploads_dir=data / "uploads",
        static_dir=tmp_path / "no-static",
    )


def add_user(paths: AppPaths, login: str, role: str) -> None:
    conn = connect(paths.db_file)
    try:
        create_user(conn, login, login.title(), role, PASSWORD, must_change=False)
    finally:
        conn.close()


@contextmanager
def client_for(paths: AppPaths, role: str = "manager") -> Iterator[TestClient]:
    app = create_app(paths)
    login = f"user-{role}"
    conn = connect(paths.db_file)
    try:
        exists = conn.execute("SELECT 1 FROM users WHERE login = ?", (login,)).fetchone()
    finally:
        conn.close()
    if not exists:
        add_user(paths, login, role)
    with TestClient(app) as client:
        response = client.post("/api/auth/login", json={"login": login, "password": PASSWORD})
        assert response.status_code == 200, response.text
        client.headers.update(HEADERS)
        yield client


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])
