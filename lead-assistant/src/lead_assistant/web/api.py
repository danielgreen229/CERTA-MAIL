"""HTTP API рабочего места и раздача собранного интерфейса (Starlette + uvicorn).

Каждое действие интерфейса выполняется через этот API; права проверяются здесь, а не
в интерфейсе. Изменяющие запросы требуют сессию и заголовок ``X-Requested-With``
(защита от подделки запроса с чужого сайта вместе с cookie SameSite=Strict).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from lead_assistant import __version__
from lead_assistant.backends import use_utf8_console
from lead_assistant.extract import extract
from lead_assistant.models import LeadError
from lead_assistant.storage import LeadStore
from lead_assistant.web import auth, connectors, jobs, kb, leads, quality
from lead_assistant.web.config import AppPaths
from lead_assistant.web.db import audit, connect, get_settings, init_db, lead_key, put_setting

logger = logging.getLogger("lead_assistant.api")
COOKIE = "leads_session"
type Handler = Callable[[Request], Response]


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def create_app(paths: AppPaths) -> Starlette:
    paths.ensure()
    init_db(paths.db_file)
    with contextlib.closing(connect(paths.db_file)) as conn:
        password = auth.bootstrap_admin(conn, paths.data_dir / "initial-admin.txt")
    if password:
        logger.warning(
            "создан администратор admin; начальный пароль записан в %s (смените при входе)",
            paths.data_dir / "initial-admin.txt",
        )
    store = LeadStore(paths.leads_file)

    @contextlib.contextmanager
    def db() -> Iterator[sqlite3.Connection]:
        conn = connect(paths.db_file)
        try:
            yield conn
        finally:
            conn.close()

    def current_user(
        request: Request, conn: sqlite3.Connection, role: str = "manager"
    ) -> auth.User:
        user = auth.user_by_token(conn, request.cookies.get(COOKIE))
        if user is None:
            raise ApiError(401, "UNAUTHENTICATED", "Войдите в систему")
        if request.method != "GET" and request.headers.get("x-requested-with") != "lead-assistant":
            raise ApiError(403, "CSRF", "Запрос без заголовка приложения отклонён")
        if user.must_change_password and request.url.path not in (
            "/api/auth/me",
            "/api/auth/password",
            "/api/auth/logout",
        ):
            raise ApiError(403, "PASSWORD_CHANGE_REQUIRED", "Смените начальный пароль")
        if not user.has_role(role):
            raise ApiError(403, "FORBIDDEN", "Недостаточно прав для этого действия")
        return user

    async def body(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ApiError(400, "BAD_JSON", "Тело запроса — не JSON") from error
        if not isinstance(data, dict):
            raise ApiError(400, "BAD_JSON", "Ожидается JSON-объект")
        return data

    # --- вход ---------------------------------------------------------------

    async def login(request: Request) -> Response:
        data = await body(request)
        with db() as conn:
            try:
                user, token = auth.login(
                    conn, str(data.get("login", "")), str(data.get("password", ""))
                )
            except auth.AuthError as error:
                raise ApiError(401, error.code, error.message) from error
        response = JSONResponse({"user": user.to_dict()})
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            samesite="strict",
            max_age=auth.SESSION_DAYS * 86400,
            secure=request.url.scheme == "https",
        )
        return response

    def logout(request: Request) -> Response:
        with db() as conn:
            token = request.cookies.get(COOKIE)
            if token:
                auth.logout(conn, token)
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE)
        return response

    def me(request: Request) -> Response:
        with db() as conn:
            user = current_user(request, conn)
            settings = get_settings(conn)
        return JSONResponse(
            {
                "user": user.to_dict(),
                "version": __version__,
                "demo_settings": bool(settings.get("demo")),
            }
        )

    async def change_password(request: Request) -> Response:
        data = await body(request)
        with db() as conn:
            user = current_user(request, conn)
            try:
                auth.change_password(conn, user, str(data.get("old", "")), str(data.get("new", "")))
            except auth.AuthError as error:
                raise ApiError(400, error.code, error.message) from error
        (paths.data_dir / "initial-admin.txt").unlink(missing_ok=True)
        return JSONResponse({"ok": True})

    # --- заявки -------------------------------------------------------------

    def list_leads(request: Request) -> Response:
        with db() as conn:
            current_user(request, conn)
            views = leads.all_views(conn, store)
            filtered = leads.filter_views(views, dict(request.query_params))
            counts = {
                "total": len(views),
                "new": sum(v.state == "new" for v in views),
                "pending": sum(v.state == "pending" for v in views),
                "needs_review": sum(v.summary()["needs_review"] for v in views),
                "high": sum(v.lead.get("priority") == "high" for v in views),
                "overdue": sum(v.summary()["overdue"] for v in views),
            }
            active = jobs.active_job(conn)
        return JSONResponse(
            {"leads": [v.summary() for v in filtered], "counts": counts, "active_job": active}
        )

    def full_detail(conn: sqlite3.Connection, user: auth.User, key: str) -> dict[str, Any]:
        """Карточка заявки целиком — одна и та же для чтения и для ответа на решение."""
        view = leads.find_view(conn, store, key)
        detail = view.detail(leads.history(conn, key))
        detail["knowledge"] = kb.search(conn, user, str(view.lead.get("text") or ""), limit=3)
        shipments = []
        for item in view.extraction["fields"].get("order") or []:
            status = connectors.shipment_status(conn, str(item["value"]["number"]))
            if status:
                shipments.append(status)
        detail["shipments"] = shipments
        return detail

    def lead_detail(request: Request) -> Response:
        with db() as conn:
            user = current_user(request, conn)
            return JSONResponse(full_detail(conn, user, request.path_params["key"]))

    async def decide(request: Request) -> Response:
        key = request.path_params["key"]
        data = await body(request)
        with db() as conn:
            user = current_user(request, conn)
            outcome = leads.decide(
                conn,
                store,
                key,
                user,
                str(data.get("action")),
                data.get("result_version"),
                data.get("category"),
                data.get("priority"),
                data.get("draft_reply"),
                data.get("reason"),
            )
            detail = full_detail(conn, user, key)
        return JSONResponse({**outcome, "lead": detail})

    async def assign(request: Request) -> Response:
        key = request.path_params["key"]
        data = await body(request)
        with db() as conn:
            user = current_user(request, conn)
            leads.find_view(conn, store, key)
            leads.assign(conn, key, user, data.get("assignee"), data.get("due_at"))
        return JSONResponse({"ok": True})

    # --- задачи -------------------------------------------------------------

    async def create_job(request: Request) -> Response:
        data = await body(request)
        with db() as conn:
            user = current_user(request, conn)
            params = {k: data[k] for k in ("today", "batch_size") if data.get(k)}
            job = jobs.create_job(conn, user.id, params)
        return JSONResponse({"job": job}, status_code=202)

    def list_jobs(request: Request) -> Response:
        with db() as conn:
            current_user(request, conn)
            return JSONResponse({"jobs": jobs.list_jobs(conn)})

    def get_job(request: Request) -> Response:
        with db() as conn:
            current_user(request, conn)
            job = jobs.get_job(conn, request.path_params["job_id"])
        if job is None:
            raise ApiError(404, "NOT_FOUND", "Задача не найдена")
        return JSONResponse({"job": job})

    def cancel_job(request: Request) -> Response:
        with db() as conn:
            user = current_user(request, conn)
            jobs.cancel(conn, request.path_params["job_id"], user.id)
        return JSONResponse({"ok": True})

    # --- качество -----------------------------------------------------------

    def get_quality(request: Request) -> Response:
        with db() as conn:
            current_user(request, conn, "supervisor")
            return JSONResponse(quality.metrics(conn))

    def export_cases(request: Request) -> Response:
        with db() as conn:
            current_user(request, conn, "supervisor")
            by_key = {lead_key(lead["id"]): lead for lead in store.snapshot().leads}
            data = quality.corrections_as_cases(conn, by_key)
        return Response(
            json.dumps(data, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="manager-corrections.json"'},
        )

    # --- база знаний --------------------------------------------------------

    def kb_documents(request: Request) -> Response:
        with db() as conn:
            user = current_user(request, conn)
            return JSONResponse(
                {
                    "documents": kb.list_documents(conn, user),
                    "limits": {"max_bytes": kb.MAX_BYTES, "types": sorted(kb.ALLOWED)},
                }
            )

    async def kb_upload(request: Request) -> Response:
        async with request.form(max_files=1, max_part_size=kb.MAX_BYTES + 1024) as form:
            upload = form.get("file")
            if upload is None or isinstance(upload, str):
                raise ApiError(400, "INVALID_ARGUMENT", "Не выбран файл")
            data = await upload.read(kb.MAX_BYTES + 1)
            fields = {
                k: str(form.get(k) or "")
                for k in ("title", "version", "owner", "valid_from", "valid_to", "min_role")
            }
            filename = upload.filename or ""
        with db() as conn:
            user = current_user(request, conn, "supervisor")
            document = kb.add_document(
                conn,
                paths.uploads_dir,
                user,
                filename,
                data,
                fields["title"],
                fields["version"],
                fields["owner"],
                fields["valid_from"] or None,
                fields["valid_to"] or None,
                fields["min_role"] or "manager",
            )
        return JSONResponse({"document": document}, status_code=201)

    def kb_delete(request: Request) -> Response:
        with db() as conn:
            user = current_user(request, conn, "supervisor")
            kb.delete_document(conn, user, int(request.path_params["doc_id"]))
        return JSONResponse({"ok": True})

    def kb_search(request: Request) -> Response:
        with db() as conn:
            user = current_user(request, conn)
            return JSONResponse(kb.search(conn, user, request.query_params.get("q", ""), limit=10))

    def kb_chunk(request: Request) -> Response:
        with db() as conn:
            user = current_user(request, conn)
            return JSONResponse(kb.get_chunk(conn, user, int(request.path_params["chunk_id"])))

    # --- подключения и настройки -------------------------------------------

    def list_connectors(request: Request) -> Response:
        with db() as conn:
            current_user(request, conn)
            return JSONResponse({"connectors": connectors.list_connectors(conn)})

    async def configure_connector(request: Request) -> Response:
        data = await body(request)
        with db() as conn:
            user = current_user(request, conn, "admin")
            return JSONResponse(
                connectors.configure(conn, request.path_params["name"], data, user.id)
            )

    def check_connector(request: Request) -> Response:
        with db() as conn:
            user = current_user(request, conn, "admin")
            return JSONResponse(connectors.check(conn, request.path_params["name"], user.id))

    def import_connector(request: Request) -> Response:
        with db() as conn:
            user = current_user(request, conn, "supervisor")
            return JSONResponse(
                connectors.import_messages(conn, store, request.path_params["name"], user.id)
            )

    def get_settings_view(request: Request) -> Response:
        with db() as conn:
            current_user(request, conn)
            return JSONResponse(get_settings(conn))

    async def put_settings(request: Request) -> Response:
        data = await body(request)
        allowed = ("timezone", "work_hours", "sla_hours", "assignment", "model")
        with db() as conn:
            user = current_user(request, conn, "admin")
            for key in allowed:
                if key in data:
                    _validate_setting(key, data[key])
                    put_setting(conn, key, data[key])
            put_setting(conn, "demo", False)
            audit(
                conn,
                "settings_changed",
                user.id,
                "settings",
                keys=[k for k in allowed if k in data],
            )
            return JSONResponse(get_settings(conn))

    def list_users(request: Request) -> Response:
        with db() as conn:
            current_user(request, conn, "admin")
            return JSONResponse({"users": [u.to_dict() for u in auth.list_users(conn)]})

    async def create_user(request: Request) -> Response:
        data = await body(request)
        with db() as conn:
            admin = current_user(request, conn, "admin")
            try:
                user = auth.create_user(
                    conn,
                    str(data.get("login", "")),
                    str(data.get("name", "")),
                    str(data.get("role", "")),
                    str(data.get("password", "")),
                    True,
                    admin.id,
                )
            except auth.AuthError as error:
                raise ApiError(400, error.code, error.message) from error
        return JSONResponse({"user": user.to_dict()}, status_code=201)

    def audit_log(request: Request) -> Response:
        with db() as conn:
            current_user(request, conn, "supervisor")
            rows = conn.execute(
                "SELECT a.*, u.name AS user_name FROM audit a "
                "LEFT JOIN users u ON u.id = a.user_id "
                "ORDER BY a.id DESC LIMIT 200"
            ).fetchall()
        return JSONResponse(
            {
                "events": [
                    {
                        "ts": r["ts"],
                        "user": r["user_name"],
                        "action": r["action"],
                        "target": r["target"],
                        "details": json.loads(r["details"]),
                    }
                    for r in rows
                ]
            }
        )

    def preview_extract(request: Request) -> Response:
        with db() as conn:
            current_user(request, conn)
        text = request.query_params.get("text", "")
        return JSONResponse(extract({"text": text}).to_dict())

    def health(_request: Request) -> Response:
        problems = []
        try:
            count = len(store.snapshot().leads)
        except LeadError as error:
            problems.append(f"leads.json: {error.code.value}")
            count = None
        with db() as conn:
            conn.execute("SELECT 1").fetchone()
            active = jobs.active_job(conn)
            beat = active["heartbeat_at"] if active else None
        return JSONResponse(
            {
                "ok": not problems,
                "version": __version__,
                "leads": count,
                "problems": problems,
                "active_job": active["id"] if active else None,
                "worker_heartbeat": beat,
            },
            status_code=200 if not problems else 503,
        )

    # --- раздача интерфейса ------------------------------------------------

    def spa(request: Request) -> Response:
        index = paths.static_dir / "index.html"
        if request.url.path.startswith("/api/"):
            raise ApiError(404, "NOT_FOUND", "Нет такого метода API")
        if not index.exists():
            return Response(
                "Интерфейс не собран: выполните сборку web/ (npm run build).",
                status_code=503,
                media_type="text/plain; charset=utf-8",
            )
        return FileResponse(index)

    routes: list[Route | Mount] = [
        Route("/api/health", health),
        Route("/api/auth/login", login, methods=["POST"]),
        Route("/api/auth/logout", logout, methods=["POST"]),
        Route("/api/auth/me", me),
        Route("/api/auth/password", change_password, methods=["POST"]),
        Route("/api/leads", list_leads),
        Route("/api/leads/{key:path}/decision", decide, methods=["POST"]),
        Route("/api/leads/{key:path}/assign", assign, methods=["POST"]),
        Route("/api/leads/{key:path}", lead_detail),
        Route("/api/jobs", list_jobs),
        Route("/api/jobs", create_job, methods=["POST"]),
        Route("/api/jobs/{job_id}", get_job),
        Route("/api/jobs/{job_id}/cancel", cancel_job, methods=["POST"]),
        Route("/api/quality", get_quality),
        Route("/api/quality/cases", export_cases),
        Route("/api/kb/documents", kb_documents),
        Route("/api/kb/documents", kb_upload, methods=["POST"]),
        Route("/api/kb/documents/{doc_id:int}", kb_delete, methods=["DELETE"]),
        Route("/api/kb/search", kb_search),
        Route("/api/kb/chunks/{chunk_id:int}", kb_chunk),
        Route("/api/connectors", list_connectors),
        Route("/api/connectors/{name}", configure_connector, methods=["PUT"]),
        Route("/api/connectors/{name}/check", check_connector, methods=["POST"]),
        Route("/api/connectors/{name}/import", import_connector, methods=["POST"]),
        Route("/api/settings", get_settings_view),
        Route("/api/settings", put_settings, methods=["PUT"]),
        Route("/api/users", list_users),
        Route("/api/users", create_user, methods=["POST"]),
        Route("/api/audit", audit_log),
        Route("/api/extract", preview_extract),
    ]
    assets = paths.static_dir / "assets"
    if assets.is_dir():
        routes.append(Mount("/assets", StaticFiles(directory=assets), name="assets"))
    routes.append(Route("/{path:path}", spa))

    def on_error(_request: Request, exc: Exception) -> Response:
        if isinstance(exc, ApiError):
            status, code, message, details = exc.status, exc.code, exc.message, exc.details
        elif isinstance(exc, leads.DecisionError):
            status = {"NOT_FOUND": 404, "CONFLICT": 409, "DUPLICATE": 409}.get(exc.code, 400)
            code, message, details = exc.code, exc.message, exc.details
        elif isinstance(exc, jobs.JobError):
            status, code, message, details = 409, exc.code, exc.message, exc.details
        elif isinstance(exc, kb.KbError):
            status = 404 if exc.code == "NOT_FOUND" else 413 if exc.code == "TOO_LARGE" else 400
            code, message, details = exc.code, exc.message, {}
        elif isinstance(exc, connectors.ConnectorError):
            status = 404 if exc.code == "NOT_FOUND" else 409
            code, message, details = exc.code, exc.message, {}
        elif isinstance(exc, LeadError):
            status = {"NOT_FOUND": 404, "CONFLICT": 409, "INVALID_ARGUMENT": 400}.get(
                exc.code.value, 503
            )
            code, message, details = exc.code.value, exc.message, exc.details
        elif isinstance(exc, HTTPException):
            status, code, message, details = exc.status_code, "HTTP", str(exc.detail), {}
        else:
            logger.exception("необработанная ошибка API")
            status, code, message, details = 500, "INTERNAL", "Внутренняя ошибка сервера", {}
        return JSONResponse(
            {"error": {"code": code, "message": message, **_jsonable(details)}}, status_code=status
        )

    exception_handlers: dict[Any, Any] = {
        Exception: on_error,
        ApiError: on_error,
        HTTPException: on_error,
        LeadError: on_error,
        leads.DecisionError: on_error,
        jobs.JobError: on_error,
        kb.KbError: on_error,
        connectors.ConnectorError: on_error,
    }
    return Starlette(routes=routes, exception_handlers=exception_handlers)


def _jsonable(details: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(json.dumps(details, ensure_ascii=False, default=str))
    return result


def _validate_setting(key: str, value: Any) -> None:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    if key == "timezone":
        try:
            ZoneInfo(str(value))
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ApiError(400, "INVALID_ARGUMENT", f"Неизвестный часовой пояс: {value}") from error
    elif key == "sla_hours":
        if not isinstance(value, dict) or not all(
            k in ("high", "medium", "low") and isinstance(v, (int, float)) and v > 0
            for k, v in value.items()
        ):
            raise ApiError(400, "INVALID_ARGUMENT", "Сроки реакции — положительные часы")
    elif key == "work_hours":
        if not (
            isinstance(value, dict)
            and 0 <= value.get("start", -1) < value.get("end", -1) <= 24
            and isinstance(value.get("days"), list)
        ):
            raise ApiError(400, "INVALID_ARGUMENT", "Рабочие часы: start < end, список дней")
    elif not isinstance(value, dict):
        raise ApiError(400, "INVALID_ARGUMENT", f"{key}: ожидается объект")


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(prog="leads-web", description="Рабочее место менеджера")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    import os

    from lead_assistant.web.config import ENV_HOST, ENV_PORT

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    paths = AppPaths.from_env()
    app = create_app(paths)
    host = args.host or os.environ.get(ENV_HOST) or "127.0.0.1"
    port = args.port or int(os.environ.get(ENV_PORT) or 8000)
    uvicorn.run(app, host=host, port=port, log_level="info", proxy_headers=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["Path", "create_app", "main"]
