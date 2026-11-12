"""Приёмочный сценарий рабочего места через обычные точки входа.

    python -m lead_assistant.web.acceptance --url http://127.0.0.1:8000 --admin-password-file …

Запускается рядом с работающим приложением (в Docker: ``docker compose exec web …``):
1. вход администратора (при первом входе — смена начального пароля);
2. постановка задачи «Обработать новые» через API и ожидание её завершения фоновым
   обработчиком с реальной моделью;
3. сверка ``leads.json`` с оригиналом по ID и полям (``lead_assistant.verify``);
4. повторная задача: ноль новых заявок, контрольная сумма файла не меняется;
5. решения менеджера (принять / исправить / отклонить) и показатели качества.
Печатает построчный отчёт и итог; код возврата 0 — все шаги пройдены.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from lead_assistant.backends import use_utf8_console
from lead_assistant.storage import sha256_hex
from lead_assistant.verify import main as verify_main
from lead_assistant.web.config import AppPaths


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def call(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "X-Requested-With": "lead-assistant"},
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"null")


def step(ok: bool, title: str, detail: str = "") -> bool:
    print(
        f"--- {'PASS' if ok else 'FAIL'}: {title}" + (f" — {detail}" if detail else ""), flush=True
    )
    return ok


def wait_job(client: Client, job_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        _, data = client.call("GET", f"/api/jobs/{job_id}")
        job: dict[str, Any] = data["job"]
        progress = job.get("progress") or {}
        line = f"{job['state']} {progress.get('done', 0)}/{progress.get('total', '?')}"
        if line != last:
            print(f"    задача {job_id}: {line}", flush=True)
            last = line
        if job["state"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(3)
    raise TimeoutError(f"задача {job_id} не завершилась за {timeout:.0f} с")


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(prog="python -m lead_assistant.web.acceptance")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--original", default=os.environ.get("LEADS_SEED_FILE"))
    parser.add_argument("--timeout", type=float, default=7200)
    args = parser.parse_args(argv)
    paths = AppPaths.from_env()
    original = Path(args.original or "data/leads.original.json")
    client = Client(args.url)
    results: list[bool] = []

    status, health = client.call("GET", "/api/health")
    results.append(step(status == 200 and health["ok"], "приложение отвечает", str(health)))

    secret = paths.data_dir / "initial-admin.txt"
    password_file = paths.data_dir / "acceptance-admin.txt"
    if secret.exists():
        initial = secret.read_text(encoding="utf-8").split("пароль: ")[1].split("\n")[0]
        client.call("POST", "/api/auth/login", {"login": "admin", "password": initial})
        new_password = "acc-" + secrets.token_urlsafe(12)
        status, _ = client.call("POST", "/api/auth/password", {"old": initial, "new": new_password})
        password_file.write_text(new_password, encoding="utf-8")
        password_file.chmod(0o600)
        results.append(step(status == 200, "первый вход: начальный пароль сменён"))
    status, _ = client.call(
        "POST",
        "/api/auth/login",
        {"login": "admin", "password": password_file.read_text(encoding="utf-8").strip()},
    )
    results.append(step(status == 200, "вход администратора"))

    before = sha256_hex(paths.leads_file.read_bytes())
    status, data = client.call("POST", "/api/jobs", {})
    results.append(
        step(status == 202, "задача поставлена из API", str(data.get("job", data))[:120])
    )
    twice, _ = client.call("POST", "/api/jobs", {})
    results.append(step(twice == 409, "второй запуск отклонён, пока идёт первый"))
    job = wait_job(client, data["job"]["id"], args.timeout)
    summary = job.get("summary") or {}
    counts = summary.get("counts") or {}
    results.append(
        step(
            job["state"] == "done" and counts.get("failed", 1) == 0,
            "реальный прогон модели в фоновом обработчике",
            f"модель {summary.get('model')}, счётчики {counts}, прогоны {job['run_ids']}",
        )
    )
    print("    сводка для руководителя:")
    for line in (summary.get("text") or "").splitlines()[:16]:
        print(f"      {line}")

    print("    сверка leads.json с оригиналом по ID и полям:")
    verified = verify_main([str(original), str(paths.leads_file), "--expect-all-processed"]) == 0
    results.append(step(verified, "сверка файла по ID и полям"))
    after = sha256_hex(paths.leads_file.read_bytes())
    results.append(step(after != before, "файл изменён прогоном", f"sha256 {after}"))

    status, data = client.call("POST", "/api/jobs", {})
    repeat = wait_job(client, data["job"]["id"], 600)
    unchanged = sha256_hex(paths.leads_file.read_bytes()) == after
    results.append(
        step(
            repeat["state"] == "done"
            and (repeat["summary"] or {}).get("counts", {}).get("found") == 0
            and unchanged,
            "повторный запуск: ноль новых, контрольная сумма прежняя",
            f"sha256 {sha256_hex(paths.leads_file.read_bytes())}",
        )
    )

    _, listing = client.call("GET", "/api/leads")
    leads = listing["leads"]
    results.append(
        step(
            all(lead["state"] == "pending" for lead in leads) and listing["counts"]["new"] == 0,
            "все заявки ждут решения менеджера",
            f"на проверку {listing['counts']['needs_review']}, срочных {listing['counts']['high']}",
        )
    )
    first, second, third = leads[0], leads[1], leads[2]
    s1, _ = client.call(
        "POST",
        f"/api/leads/{first['key']}/decision",
        {"action": "accept", "result_version": first["result_version"]},
    )
    _, detail = client.call("GET", f"/api/leads/{second['key']}")
    corrected_priority = "high" if detail["priority"] != "high" else "medium"
    s2, _ = client.call(
        "POST",
        f"/api/leads/{second['key']}/decision",
        {
            "action": "correct",
            "result_version": second["result_version"],
            "category": detail["category"],
            "priority": corrected_priority,
            "draft_reply": detail["result"]["draft_reply"],
        },
    )
    s3, _ = client.call(
        "POST",
        f"/api/leads/{third['key']}/decision",
        {"action": "reject", "result_version": third["result_version"], "reason": "приёмка"},
    )
    stale, _ = client.call(
        "POST",
        f"/api/leads/{first['key']}/decision",
        {"action": "accept", "result_version": 999},
    )
    _, quality = client.call("GET", "/api/quality")
    results.append(
        step(
            (s1, s2, s3, stale) == (200, 200, 200, 409) and quality["decided"] == 3,
            "решения менеджера по версии результата и показатели качества",
            f"доля принятых без правок {quality['accepted_share']}",
        )
    )
    passed = all(results)
    print(f"ИТОГ: {'пройдено' if passed else 'есть ошибки'} ({sum(results)}/{len(results)})")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
