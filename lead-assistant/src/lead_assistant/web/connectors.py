"""Внешние подключения: почта (IMAP), Telegram, REST-коннектор к CRM/TMS/тарифам/статусам.

Подключение активно только после ввода параметров и успешной проверки. Без них
приложение работает на локальном JSON. Импорт нормализует сообщение в формат заявки
и защищён от повторов: внешний идентификатор хранится и в SQLite, и в самой заявке
(поле ``source_id``), поэтому падение между двумя записями не приводит к дублю.
Исходящих действий (отправки ответов клиентам) в этой версии нет.
"""

from __future__ import annotations

import base64
import email
import email.header
import email.policy
import email.utils
import imaplib
import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
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
            ("host", "port", "user", "password", "folder", "smtp_host", "smtp_port"),
            "Импорт последних 50 писем папки как заявок channel=email (письма не помечаются "
            "прочитанными). Повтор по Message-ID исключён.",
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


_EXTRA_MAILBOX = re.compile(r"email-(\d+)")


def spec_for(name: str) -> Spec:
    """Описание подключения. Дополнительные почтовые ящики (email-2, email-3…) — та же «Почта»."""
    if name in SPECS:
        return SPECS[name]
    if _EXTRA_MAILBOX.fullmatch(name):
        return SPECS["email"]
    raise ConnectorError("NOT_FOUND", f"Нет подключения {name}")


def is_mailbox(name: str) -> bool:
    return name == "email" or bool(_EXTRA_MAILBOX.fullmatch(name))


def mailbox_names(conn: sqlite3.Connection) -> list[str]:
    """Все почтовые ящики: основной «email» и добавленные администратором."""
    extra = [
        row[0]
        for row in conn.execute("SELECT name FROM connectors WHERE name LIKE 'email-%'")
        if _EXTRA_MAILBOX.fullmatch(row[0])
    ]
    return ["email", *sorted(extra, key=lambda name: int(name.split("-")[1]))]


def add_mailbox(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    numbers = [int(name.split("-")[1]) for name in mailbox_names(conn)[1:]]
    name = f"email-{max(numbers, default=1) + 1}"
    with transaction(conn):
        conn.execute(
            "INSERT INTO connectors(name, config, state) VALUES (?, '{}', 'not_configured')",
            (name,),
        )
        audit(conn, "connector_added", user_id, f"connector:{name}")
    return _public(_load(conn, name))


def remove_mailbox(conn: sqlite3.Connection, name: str, user_id: int) -> None:
    if not _EXTRA_MAILBOX.fullmatch(name):
        raise ConnectorError("NOT_REMOVABLE", "Удалить можно только добавленный почтовый ящик")
    with transaction(conn):
        deleted = conn.execute("DELETE FROM connectors WHERE name = ?", (name,)).rowcount
        if not deleted:
            raise ConnectorError("NOT_FOUND", f"Нет подключения {name}")
        audit(conn, "connector_removed", user_id, f"connector:{name}")


def _load(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    spec_for(name)
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


def env_presets(environ: Mapping[str, str]) -> dict[str, dict[str, str]]:
    """Параметры подключений из окружения: ``LEADS_<ИМЯ>_<ПОЛЕ>``, например LEADS_EMAIL_HOST.

    Так администратор задаёт подключение по умолчанию в ``.env`` (не в репозитории),
    а пароль не попадает ни в код, ни в образ.
    """
    presets: dict[str, dict[str, str]] = {}
    for name, spec in SPECS.items():
        values = {
            field: environ[key].strip()
            for field in spec.fields
            if (key := f"LEADS_{name.upper()}_{field.upper()}") in environ and environ[key].strip()
        }
        if values:
            presets[name] = values
    return presets


def apply_env_presets(
    conn: sqlite3.Connection, environ: Mapping[str, str], user_id: int
) -> dict[str, str]:
    """Настраивает из окружения подключения, которые ещё не настроены в интерфейсе.

    Уже настроенное администратором не перезаписывается. Если все обязательные поля
    заданы, подключение сразу проверяется. Возвращает {имя: состояние}.
    """
    applied: dict[str, str] = {}
    for name, values in env_presets(environ).items():
        if _load(conn, name)["state"] != "not_configured":
            continue
        record = configure(conn, name, values, user_id)
        if record["state"] == "configured":
            record = check(conn, name, user_id)
        applied[name] = record["state"]
    return applied


def _public(record: dict[str, Any]) -> dict[str, Any]:
    spec = spec_for(record["name"])
    mailbox = str(record["config"].get("user") or "").strip()
    config = {
        key: (
            "••••••"
            if key in SECRET_KEYS and record["config"].get(key)
            else record["config"].get(key)
        )
        for key in spec.fields
    }
    return {
        "name": record["name"],
        "title": f"Почта: {mailbox}" if spec.kind == "imap" and mailbox else spec.title,
        "removable": bool(_EXTRA_MAILBOX.fullmatch(record["name"])),
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
    names = [*mailbox_names(conn), *(name for name in SPECS if name != "email")]
    return [_public(_load(conn, name)) for name in names]


def configure(
    conn: sqlite3.Connection, name: str, values: dict[str, Any], user_id: int
) -> dict[str, Any]:
    record = _load(conn, name)
    spec = spec_for(name)
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
    spec = spec_for(name)
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


def imap_folder(name: str) -> str:
    """Имя папки в «modified UTF-7» (RFC 3501): так IMAP-серверы хранят «Заявки» и т. п.

    ASCII-символы остаются как есть («&» → «&-»), остальные — base64 от UTF-16BE
    между «&» и «-», с «,» вместо «/». Уже закодированное имя не меняется.
    """
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            encoded = base64.b64encode("".join(run).encode("utf-16-be")).decode("ascii")
            out.append("&" + encoded.rstrip("=").replace("/", ",") + "-")
            run.clear()

    for char in name:
        if 0x20 <= ord(char) <= 0x7E:
            flush()
            out.append("&-" if char == "&" and not _is_utf7(name) else char)
        else:
            run.append(char)
    flush()
    return "".join(out)


def _is_utf7(name: str) -> bool:
    """Имя уже в modified UTF-7 (например, скопировано из списка папок сервера)."""
    return name.isascii() and "&" in name and "-" in name.split("&", 1)[1]


def _imap(config: dict[str, Any]) -> imaplib.IMAP4:
    port = int(config.get("port") or 993)
    client: imaplib.IMAP4 = (
        imaplib.IMAP4_SSL(config["host"], port, timeout=TIMEOUT)
        if port == 993
        else imaplib.IMAP4(config["host"], port, timeout=TIMEOUT)
    )
    client.login(config["user"], config["password"])
    folder = imap_folder(str(config.get("folder") or "INBOX"))
    status, _ = client.select(f'"{folder}"', readonly=True)
    if status != "OK":
        raise ConnectorError("CHECK_FAILED", "папка недоступна")
    return client


def _telegram_url(config: dict[str, Any], method: str, query: dict[str, Any] | None = None) -> str:
    base = config.get("api_base") or "https://api.telegram.org"
    url = _join(base, f"bot{config['bot_token']}/{method}")
    return url + ("?" + urllib.parse.urlencode(query) if query else "")


class _HtmlText(HTMLParser):
    BLOCKS = frozenset({"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _HtmlText()
    parser.feed(markup)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def normalize_email(raw: bytes) -> dict[str, Any]:
    message = email.message_from_bytes(raw)
    # Современный разбор заголовков понимает и RFC 2047, и «сырой» UTF-8 (SMTPUTF8).
    headers = email.message_from_bytes(raw, policy=email.policy.default)
    name, address = email.utils.parseaddr(str(headers.get("From") or ""))
    bodies: dict[str, str] = {}
    for part in message.walk() if message.is_multipart() else [message]:
        kind = part.get_content_type()
        if kind in ("text/plain", "text/html") and not part.get_filename() and kind not in bodies:
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                bodies[kind] = payload.decode(part.get_content_charset() or "utf-8", "replace")
    # Письмо только в HTML (рассылки, часть клиентов) не должно терять тело.
    plain = (bodies.get("text/plain") or "").strip()
    body = plain or html_to_text(bodies.get("text/html") or "")
    subject = str(headers.get("Subject") or "").strip()
    # Тема часто несёт суть («Груз повреждён — накладная 55120»), поэтому входит в текст.
    if subject and body and subject.lower() not in body.lower():
        text = f"Тема: {subject}\n{body}"
    else:
        text = body or subject
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
            # Тема хранится отдельно: по ней строится «Re: …» в ответе клиенту.
            **({"subject": subject[:300]} if subject else {}),
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
    if is_mailbox(name):
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
    # Ящик, в который пришло письмо: по нему в списке заявок строятся вкладки.
    inbox = str(config.get("user") or "").strip().lower() if is_mailbox(name) else None
    return _store_imported(conn, store, name, items, user_id, inbox or None)


def _store_imported(
    conn: sqlite3.Connection,
    store: LeadStore,
    channel: str,
    items: list[dict[str, Any]],
    user_id: int,
    inbox: str | None = None,
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
        fresh.append(
            {**item["lead"], "source_id": source_id, **({"inbox": inbox} if inbox else {})}
        )
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
