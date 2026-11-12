"""Фоновый обработчик: берёт задачи из SQLite и выполняет штатный прогон агента.

Прогон тот же, что у команды ``process-leads``: агент работает только через три
MCP-инструмента, раннер сверяет итог с файлом. Прогресс считается по сохранённым
данным — сколько заявок из набора задачи уже записаны в ``leads.json``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import imaplib
import logging
import signal
import sqlite3
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from pathlib import Path
from typing import Any

from lead_assistant.agent import AgentBackend
from lead_assistant.backends import open_backend, options_from_args, use_utf8_console
from lead_assistant.cli import NoModelBackend
from lead_assistant.cli import build_parser as cli_parser
from lead_assistant.llm import LlmSetupError
from lead_assistant.models import STATUS_NEW, LeadError
from lead_assistant.runner import RunConfig, run_processing
from lead_assistant.storage import LeadStore
from lead_assistant.web import connectors, jobs
from lead_assistant.web.config import AppPaths
from lead_assistant.web.db import connect, get_settings, init_db, lead_key
from lead_assistant.web.leads import analyses_from_run, sync_results

logger = logging.getLogger("lead_assistant.worker")

DEFAULT_BATCH_SIZE = 5
DEFAULT_JOB_TIMEOUT_SECONDS = 1800.0
MIN_MAIL_INTERVAL_SECONDS = 15.0
DEFAULT_MAIL_INTERVAL_SECONDS = 60.0
RECOVER_EVERY_SECONDS = 30.0
RETRY_PAUSE_SECONDS = 10.0

type BackendFactory = Callable[[Path, Callable[[str], None]], AbstractContextManager[AgentBackend]]


def backend_args(settings: dict[str, Any]) -> list[str]:
    model = settings.get("model") or {}
    args: list[str] = ["--no-download"] if model.get("no_download") else []
    if model.get("llm_url"):
        args += ["--llm-url", str(model["llm_url"])]
    if model.get("model"):
        args += ["--model", str(model["model"])]
    if model.get("build"):
        args += ["--build", str(model["build"])]
    return args


def default_backend_factory(settings: dict[str, Any]) -> BackendFactory:
    @contextmanager
    def factory(log: Path, echo: Callable[[str], None]) -> Iterator[AgentBackend]:
        options = options_from_args(cli_parser().parse_args(backend_args(settings)))
        with open_backend(options, log, echo) as backend:
            yield backend

    return factory


class Progress:
    """Считает прогресс задачи по файлу: какие заявки набора уже не new."""

    def __init__(self, store: LeadStore, ids: list[Any]) -> None:
        self.store = store
        self.ids = ids
        self.lines: list[str] = []

    def snapshot(self) -> dict[str, Any]:
        try:
            leads = {lead_key(lead["id"]): lead for lead in self.store.snapshot().leads}
        except LeadError as error:
            return {"error": error.code.value, "total": len(self.ids)}
        done = [i for i in self.ids if leads.get(lead_key(i), {}).get("status") != STATUS_NEW]
        return {
            "total": len(self.ids),
            "done": len(done),
            "done_ids": done,
            "pending_ids": [i for i in self.ids if i not in done],
            "log": self.lines[-8:],
        }


def execute_job(
    paths: AppPaths,
    job: dict[str, Any],
    factory: BackendFactory | None = None,
    heartbeat_seconds: float = 3.0,
) -> str:
    """Выполняет одну задачу и возвращает её итоговое состояние."""
    conn = connect(paths.db_file)
    store = LeadStore(paths.leads_file)
    settings = get_settings(conn)
    try:
        new_ids = [lead["id"] for lead in store.snapshot().leads if lead["status"] == STATUS_NEW]
    except LeadError as error:
        jobs.finish(
            conn, job["id"], "failed", error={"code": error.code.value, "message": error.message}
        )
        conn.close()
        return "failed"
    progress = Progress(store, new_ids)
    stop = threading.Event()

    def beat() -> None:
        beat_conn = connect(paths.db_file)
        try:
            while not stop.wait(heartbeat_seconds):
                jobs.heartbeat(beat_conn, job["id"], progress.snapshot())
        finally:
            beat_conn.close()

    jobs.heartbeat(conn, job["id"], progress.snapshot())
    thread = threading.Thread(target=beat, daemon=True)
    thread.start()

    def stop_beating() -> None:
        stop.set()
        thread.join()

    def echo(line: str) -> None:
        progress.lines.append(line)
        logger.info("%s", line)

    params = job.get("params") or {}
    config = RunConfig(
        leads_file=paths.leads_file,
        runs_dir=paths.runs_dir,
        model=str((settings.get("model") or {}).get("model") or ""),
        today=str(params.get("today") or date.today().isoformat()),
        batch_size=int(params.get("batch_size") or DEFAULT_BATCH_SIZE),
        timeout_seconds=float(params.get("timeout") or DEFAULT_JOB_TIMEOUT_SECONDS),
    )
    make_backend = factory or default_backend_factory(settings)
    run: dict[str, Any] | None = None
    try:
        if not new_ids:
            # Модель не запускается, но прогон со сверкой файла записывается: в run.json
            # видно, что новых заявок ноль и контрольная сумма файла не изменилась.
            config.skip_model_if_empty = True
            run = asyncio.run(run_processing(config, NoModelBackend(), echo=echo))
            jobs.add_run(conn, job["id"], run["run_id"])
            summary: dict[str, Any] = {**summarize(run), "text": "Новых заявок нет."}
            state = "done"
        else:
            with tempfile.NamedTemporaryFile(
                prefix="llm-server-", suffix=".log", dir=paths.runs_dir, delete=False
            ) as handle:
                log = Path(handle.name)
            with make_backend(log, echo) as backend:
                run = asyncio.run(run_processing(config, backend, echo=echo))
            if log.exists():
                if log.stat().st_size:
                    log.replace(Path(run["run_dir"]) / "llm_server.log")
                else:
                    log.unlink()
            jobs.add_run(conn, job["id"], run["run_id"])
            sync_results(conn, store.snapshot().leads, run["run_id"], analyses_from_run(run))
            summary = summarize(run)
            state = "done"
    except LlmSetupError as error:
        stop_beating()
        jobs.requeue(conn, job["id"], {"code": "LLM_SETUP", "message": str(error)})
        conn.close()
        return "queued"
    except Exception as error:  # сбой обработчика не должен терять задачу молча
        logger.exception("job %s failed", job["id"])
        stop_beating()
        jobs.finish(
            conn, job["id"], "failed", error={"code": "WORKER_ERROR", "message": str(error)}
        )
        conn.close()
        return "failed"
    stop_beating()
    jobs.heartbeat(conn, job["id"], progress.snapshot())
    run_error: dict[str, Any] | None = (run or {}).get("error")
    if (
        run_error
        and run_error.get("code") in jobs.TRANSIENT_ERRORS
        and progress.snapshot().get("pending_ids")
    ):
        requeued = jobs.requeue(conn, job["id"], run_error)
        conn.close()
        return "queued" if requeued else "failed"
    jobs.finish(conn, job["id"], state, summary=summary, error=run_error)
    conn.close()
    return state


def summarize(run: dict[str, Any]) -> dict[str, Any]:
    reconciliation = run.get("reconciliation") or {}
    run_dir = Path(run["run_dir"])
    text_path = run_dir / "summary.md"
    return {
        "run_id": run["run_id"],
        "status": run.get("status"),
        "text": text_path.read_text(encoding="utf-8") if text_path.exists() else "",
        "counts": reconciliation.get("counts"),
        "failed": reconciliation.get("failed"),
        "urgent": [
            {
                "id": entry["id"],
                "basis": entry.get("urgency_basis"),
                "next": entry.get("next_action"),
            }
            for entry in reconciliation.get("leads") or []
            if entry.get("priority") == "high"
        ],
        "metrics": run.get("metrics"),
        "model": (run.get("runtime") or {}).get("model"),
    }


def check_mail(paths: AppPaths, conn: sqlite3.Connection) -> int:
    """Забирает новые письма и сообщения из всех подключённых источников.

    Если что-то пришло и включён автоматический разбор, ставит задачу обработки
    (если другая уже идёт, новые письма разберёт следующая). Возвращает число новых.
    """
    settings = get_settings(conn).get("mail_check") or {}
    admin = conn.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()
    if admin is None:
        return 0
    store = LeadStore(paths.leads_file)
    imported = 0
    for item in connectors.list_connectors(conn):
        if item["kind"] not in ("imap", "telegram") or item["state"] != "ok":
            continue
        try:
            result = connectors.import_messages(conn, store, item["name"], int(admin[0]))
        except (connectors.ConnectorError, OSError, ValueError, imaplib.IMAP4.error) as error:
            logger.warning("проверка %s не удалась: %s", item["name"], error)
            continue
        if result["imported"]:
            logger.info("%s: новых писем %s", item["name"], result["imported"])
        imported += int(result["imported"])
    # Разбор ставится, пока есть неразобранные письма: пришедшие во время другой задачи
    # не остаются висеть — их возьмёт следующая проверка.
    if settings.get("auto_process", True) and any(
        lead.get("status") == STATUS_NEW for lead in store.snapshot().leads
    ):
        with contextlib.suppress(jobs.JobError):
            jobs.create_job(conn, int(admin[0]), {"source": "mail_check"})
    return imported


def run_forever(paths: AppPaths, poll_seconds: float = 2.0, once: bool = False) -> None:
    init_db(paths.db_file)
    conn = connect(paths.db_file)
    stopping = threading.Event()

    def handle_signal(_signum: int, _frame: object) -> None:
        stopping.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handle_signal)

    recovered = jobs.recover_stale(conn)
    if recovered:
        logger.info("восстановлены задачи после остановки обработчика: %s", recovered)
    logger.info("обработчик запущен: %s", paths.leads_file)
    last_recover = time.monotonic()
    last_mail = 0.0
    while not stopping.is_set():
        mail = get_settings(conn).get("mail_check") or {}
        interval = max(
            MIN_MAIL_INTERVAL_SECONDS,
            float(mail.get("interval_seconds") or DEFAULT_MAIL_INTERVAL_SECONDS),
        )
        if not once and mail.get("enabled", True) and time.monotonic() - last_mail >= interval:
            last_mail = time.monotonic()
            try:
                check_mail(paths, conn)
            except Exception:  # проверка почты не должна останавливать обработчик
                logger.exception("ошибка проверки почты")
        job = jobs.claim_next(conn)
        if job is None:
            if once:
                break
            if time.monotonic() - last_recover > RECOVER_EVERY_SECONDS:
                jobs.recover_stale(conn)
                last_recover = time.monotonic()
            stopping.wait(poll_seconds)
            continue
        logger.info("задача %s: попытка %s", job["id"], job["attempts"])
        state = execute_job(paths, job)
        logger.info("задача %s: %s", job["id"], state)
        if state == "queued":
            stopping.wait(RETRY_PAUSE_SECONDS)  # пауза перед повтором после временной ошибки
    conn.close()


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(prog="leads-worker", description="Фоновый обработчик заявок")
    parser.add_argument("--once", action="store_true", help="выполнить очередь и выйти")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    paths = AppPaths.from_env()
    paths.ensure()
    run_forever(paths, once=args.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["execute_job", "main", "run_forever"]
