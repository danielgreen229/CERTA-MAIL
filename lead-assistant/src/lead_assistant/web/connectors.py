"""Внешние подключения: почта (IMAP), Telegram, REST-коннектор к CRM/TMS/тарифам/статусам.

Подключение активно только после ввода параметров и успешной проверки. Без них
приложение работает на локальном JSON. Импорт нормализует сообщение в формат заявки
и защищён от повторов: внешний идентификатор хранится и в SQLite, и в самой заявке
(поле ``source_id``), поэтому падение между двумя записями не приводит к дублю.
Исходящих действий (отправки ответов клиентам) в этой версии нет.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from lead_assistant.storage import LeadStore
from lead_assistant.web.db import audit, transaction, utc_now

TIMEOUT = 10.0
SECRET_KEYS = ("password", "token", "bot_token", "api_key")


@dataclass(frozen=True)
class Spec:
    name: str
    title: str
    kind: str  # imap | telegram | rest
    fields: tuple[str, ...]
    contract: str


SPECS: dict[str, Spec] = {
    spec.name: spec
    for spec in (
        Spec(
            "email",
            "Почта (IMAP)",
            "imap",
            ("host", "port", "user", "password", "folder"),
            "Импорт непрочитанных писем папки как заявок channel=email. Повтор по Message-ID "
            "исключён.",
        ),
        Spec(
            "telegram",
            "Telegram-бот",
            "telegram",
            ("bot_token", "api_base"),
            "Импорт сообщений боту (getUpdates) как заявок channel=telegram. Повтор по "
            "update_id исключён.",
        ),
        Spec(
            "crm",
            "CRM",
            "rest",
            ("base_url", "api_key", "health_path", "lead_path"),
            "GET {health_path} → 200; GET {lead_path} с подстановкой {id} → JSON заявки. "
            "Запись результата в CRM — следующий этап (через очередь исходящих операций).",
        ),
        Spec(
            "tms",
            "TMS / статусы перевозок",
            "rest",
            ("base_url", "api_key", "health_path", "status_path"),
            'GET {status_path} с подстановкой {number} → {"number", "status", '
            '"eta", "updated_at"}. В карточке показывается с источником и временем '
            "получения.",
        ),
        Spec(
            "tariffs",
            "Тарифы",
            "rest",
            ("base_url", "api_key", "health_path", "quote_path"),
            'GET {quote_path}?from=&to=&kg= → {"price", "currency", "valid_until"}. '
            "Цены в черновик агент не пишет; менеджер видит расчёт с источником.",
        ),
    )
}


class ConnectorError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _load(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    if name not in SPECS:
        raise ConnectorError("NOT_FOUND", f"Нет подключения {name}")
    row = conn.execute("SELECT * FROM connectors WHERE name = ?", (name,)).fetchone()
    if row is None:
        return {
            "name": name,
            "config": {},
            "state": "not_configured",
            "checked_at": None,
            "detail": None,
        }
    return {
        "name": name,
        "config": json.loads(row["config"]),
        "state": row["state"],
        "checked_at": row["checked_at"],
        "detail": row["detail"],
    }


def _public(record: dict[str, Any]) -> dict[str, Any]:
    spec = SPECS[record["name"]]
    config = {
        key: (
            "••••••"
            if key in SECRET_KEYS and record["config"].get(key)
            else record["config"].get(key)
        )
        for key in spec.fields
    }
    return {
        "name": spec.name,
        "title": spec.title,
        "kind": spec.kind,
        "fields": list(spec.fields),
        "contract": spec.contract,
        "config": config,
        "state": record["state"],
        "checked_at": record["checked_at"],
        "detail": record["detail"],
        "test_service": bool(record["config"].get("test_service")),
    }


def list_connectors(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_public(_load(conn, name)) for name in SPECS]


def configure(
    conn: sqlite3.Connection, name: str, values: dict[str, Any], user_id: int
) -> dict[str, Any]:
    record = _load(conn, name)
    spec = SPECS[name]
    config = dict(record["config"])
    for key in spec.fields:
        if key in values:
            value = values[key]
            if key in SECRET_KEYS and value in ("••••••", None):
                continue  # маска секрета не перезаписывает сохранённое значение
            config[key] = str(value).strip() if value is not None else ""
    if "test_service" in values:
        config["test_service"] = bool(values["test_service"])
    configured = all(config.get(key) for key in _required(spec))
    with transaction(conn):
        conn.execute(
            "INSERT INTO connectors(name, config, state) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET config = excluded.config, state = excluded.state, "
            "detail = NULL, checked_at = NULL",
            (name, json.dumps(config), "configured" if configured else "not_configured"),
        )
        audit(
            conn,
            "connector_configured",
            user_id,
            f"connector:{name}",
            fields=sorted(k for k in values if k not in SECRET_KEYS),
        )
    return _public(_load(conn, name))


def _required(spec: Spec) -> tuple[str, ...]:
    if spec.kind == "imap":
        return ("host", "user", "password")
    if spec.kind == "telegram":
        return ("bot_token",)
    return ("base_url",)


def _set_state(conn: sqlite3.Connection, name: str, state: str, detail: str) -> None:
    conn.execute(
        "UPDATE connectors SET state = ?, detail = ?, checked_at = ? WHERE name = ?",
        (state, detail[:500], utc_now(), name),
    )


def _http_json(url: str, api_key: str | None = None) -> Any:
    headers = {"Accept": "application/json", "User-Agent": "lead-assistant"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = response.read()
    return json.loads(body) if body else None


def _join(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


def check(conn: sqlite3.Connection, name: str, user_id: int) -> dict[str, Any]:
    record = _load(conn, name)
    spec = SPECS[name]
    config = record["config"]
    if not all(config.get(key) for key in _required(spec)):
        raise ConnectorError("NOT_CONFIGURED", "Сначала заполните параметры подключения")
    try:
        if spec.kind == "imap":
            client = _imap(config)
            client.logout()
            detail = f"вход выполнен, папка {config.get('folder') or 'INBOX'} доступна"
        elif spec.kind == "telegram":
            data = _http_json(_telegram_url(config, "getMe"))
            if not data or not data.get("ok"):
                raise ConnectorError("CHECK_FAILED", "Telegram ответил без ok=true")
            detail = f"бот @{data['result'].get('username')} отвечает"
        else:
            _http_json(
                _join(config["base_url"], config.get("health_path") or "/health"),
                config.get("api_key"),
            )
            detail = "сервис отвечает"
        state = "ok"
    except ConnectorError as error:
        state, detail = "error", error.message
    except (OSError, urllib.error.URLError, imaplib.IMAP4.error, ValueError) as error:
        state, detail = "error", f"{type(error).__name__}: {error}"
    if config.get("test_service"):
        detail = f"ТЕСТОВЫЙ СЕРВИС: {detail}"
    _set_state(conn, name, state, detail)
    audit(conn, "connector_checked", user_id, f"connector:{name}", state=state)
    return _public(_load(conn, name))


def _imap(config: dict[str, Any]) -> imaplib.IMAP4:
    port = int(config.get("port") or 993)
    client: imaplib.IMAP4 = (
        imaplib.IMAP4_SSL(config["host"], port, timeout=TIMEOUT)
        if port == 993
        else imaplib.IMAP4(config["host"], port, timeout=TIMEOUT)
    )
    client.login(config["user"], config["password"])
    status, _ = client.select(config.get("folder") or "INBOX", readonly=True)
    if status != "OK":
        raise ConnectorError("CHECK_FAILED", "папка недоступна")
    return client


def _telegram_url(config: dict[str, Any], method: str, query: dict[str, Any] | None = None) -> str:
    base = config.get("api_base") or "https://api.telegram.org"
    url = _join(base, f"bot{config['bot_token']}/{method}")
    return url + ("?" + urllib.parse.urlencode(query) if query else "")


def _decode(value: str | None) -> str:
    if not value:
        return ""
    return str(email.header.make_header(email.header.decode_header(value)))


def normalize_email(raw: bytes) -> dict[str, Any]:
    message = email.message_from_bytes(raw)
    name, address = email.utils.parseaddr(_decode(message.get("From")))
    body = ""
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_type() == "text/plain" and not part.get_filename():
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                body = payload.decode(part.get_content_charset() or "utf-8", "replace")
                break
    subject = _decode(message.get("Subject"))
    text = body.strip() or subject
    try:
        sent = email.utils.parsedate_to_datetime(message.get("Date", "")).date().isoformat()
    except (TypeError, ValueError):
        sent = datetime.now(UTC).date().isoformat()
    return {
        "external_id": (message.get("Message-ID") or "").strip() or None,
        "lead": {
            "date": sent,
            "channel": "email",
            "name": name or address,
            "contact": address,
            "text": text[:5000],
        },
    }


def normalize_telegram(update: dict[str, Any]) -> dict[str, Any] | None:
    message = update.get("message") or {}
    text = message.get("text")
    if not text:
        return None
    sender = message.get("from") or {}
    name = " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")]))
    contact = f"@{sender['username']}" if sender.get("username") else f"tg:{sender.get('id')}"
    sent = datetime.fromtimestamp(int(message.get("date") or 0), UTC).date().isoformat()
    return {
        "external_id": str(update.get("update_id")),
        "lead": {
            "date": sent,
            "channel": "telegram",
            "name": name or contact,
            "contact": contact,
            "text": str(text)[:5000],
        },
    }


def import_messages(
    conn: sqlite3.Connection, store: LeadStore, name: str, user_id: int, limit: int = 50
) -> dict[str, Any]:
    record = _load(conn, name)
    if record["state"] != "ok":
        raise ConnectorError("NOT_READY", "Подключение не проверено — сначала «Проверить»")
    config = record["config"]
    items: list[dict[str, Any]] = []
    if name == "email":
        client = _imap(config)
        try:
            _, data = client.search(None, "ALL")
            for number in (data[0].split() if data and data[0] else [])[-limit:]:
                _, fetched = client.fetch(number, "(BODY.PEEK[])")
                for part in fetched:
                    if isinstance(part, tuple):
                        items.append(normalize_email(part[1]))
        finally:
            client.logout()
    elif name == "telegram":
        data = _http_json(_telegram_url(config, "getUpdates", {"limit": limit}))
        for update in (data or {}).get("result") or []:
            item = normalize_telegram(update)
            if item:
                items.append(item)
    else:
        raise ConnectorError("NOT_SUPPORTED", "Импорт заявок есть только для почты и Telegram")
    return _store_imported(conn, store, name, items, user_id)


def _store_imported(
    conn: sqlite3.Connection,
    store: LeadStore,
    channel: str,
    items: list[dict[str, Any]],
    user_id: int,
) -> dict[str, Any]:
    existing_sources = {
        str(lead.get("source_id")) for lead in store.snapshot().leads if lead.get("source_id")
    }
    fresh: list[dict[str, Any]] = []
    skipped = 0
    for item in items:
        external = item["external_id"]
        if not external:
            skipped += 1
            continue
        source_id = f"{channel}:{external}"
        seen = conn.execute(
            "SELECT 1 FROM imported_messages WHERE channel = ? AND external_id = ?",
            (channel, external),
        ).fetchone()
        if seen or source_id in existing_sources:
            skipped += 1
            continue
        existing_sources.add(source_id)
        fresh.append({**item["lead"], "source_id": source_id})
    ids = store.append_leads(fresh)
    with transaction(conn):
        for lead, lead_id in zip(fresh, ids, strict=True):
            channel_name, external = lead["source_id"].split(":", 1)
            conn.execute(
                "INSERT OR IGNORE INTO imported_messages(channel, external_id, lead_id, "
                "imported_at) VALUES (?, ?, ?, ?)",
                (channel_name, external, json.dumps(lead_id), utc_now()),
            )
        audit(
            conn,
            "messages_imported",
            user_id,
            f"connector:{channel}",
            imported=len(ids),
            skipped=skipped,
        )
    return {"imported": len(ids), "skipped": skipped, "ids": ids}


def shipment_status(conn: sqlite3.Connection, number: str) -> dict[str, Any] | None:
    """Статус отправления из TMS с источником и временем получения; None — нет подключения."""
    record = _load(conn, "tms")
    if record["state"] != "ok":
        return None
    config = record["config"]
    path = (config.get("status_path") or "/shipments/{number}").replace(
        "{number}", urllib.parse.quote(number)
    )
    fetched_at = utc_now()
    try:
        data = _http_json(_join(config["base_url"], path), config.get("api_key"))
    except (OSError, urllib.error.URLError, ValueError) as error:
        return {
            "number": number,
            "error": f"{type(error).__name__}: {error}",
            "source": "TMS",
            "fetched_at": fetched_at,
        }
    return {
        "number": number,
        "data": data,
        "source": ("ТЕСТОВЫЙ СЕРВИС " if config.get("test_service") else "") + config["base_url"],
        "fetched_at": fetched_at,
    }
