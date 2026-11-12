"""Отправка ответа клиенту по почте — только по явной команде менеджера.

Ответ уходит с того же ящика, что настроен в «Подключениях» → «Почта»: SMTP-сервер
берётся из полей ``smtp_host``/``smtp_port`` или выводится из IMAP-сервера
(imap.mail.ru → smtp.mail.ru:465). Письмо — ответ в той же переписке (Re: тема,
In-Reply-To исходного письма). Каждая попытка записывается в ``outgoing`` и в аудит;
повторная отправка того же обращения требует явного подтверждения (``force``).
"""

from __future__ import annotations

import json
import smtplib
import socket
import sqlite3
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from lead_assistant.storage import Lead
from lead_assistant.web import connectors
from lead_assistant.web.db import audit, lead_key, transaction, utc_now

MAX_BODY = 5000
TIMEOUT = 20.0


class OutboxError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _email_config(conn: sqlite3.Connection, lead: Lead) -> dict[str, Any] | None:
    """Ящик для ответа: тот, в который пришло письмо, иначе первый подключённый."""
    boxes: list[dict[str, Any]] = []
    for name in connectors.mailbox_names(conn):
        row = conn.execute(
            "SELECT config, state FROM connectors WHERE name = ?", (name,)
        ).fetchone()
        if row is not None and row["state"] == "ok":
            boxes.append(json.loads(row["config"]))
    inbox = str(lead.get("inbox") or "").strip().lower()
    for config in boxes:
        if inbox and str(config.get("user") or "").strip().lower() == inbox:
            return config
    return boxes[0] if boxes else None


def smtp_endpoint(config: dict[str, Any]) -> tuple[str, int]:
    host = str(config.get("smtp_host") or "").strip()
    if not host:
        imap_host = str(config.get("host") or "")
        host = "smtp." + imap_host[5:] if imap_host.startswith("imap.") else imap_host
    port = int(config.get("smtp_port") or 465)
    return host, port


def _subject(lead: Lead) -> str:
    first = str(lead.get("text") or "").split("\n", 1)[0]
    topic = str(lead.get("subject") or "").strip() or (
        first[len("Тема: ") :].strip() if first.startswith("Тема: ") else ""
    )
    if not topic:
        return "Re: ваше обращение"
    return topic if topic.lower().startswith("re:") else f"Re: {topic}"


def _original_message_id(lead: Lead) -> str | None:
    channel, _, external = str(lead.get("source_id") or "").partition(":")
    if not connectors.is_mailbox(channel):
        return None
    return external or None


def _telegram_config(conn: sqlite3.Connection, lead: Lead) -> dict[str, Any] | None:
    """Бот для ответа: тот, через которого пришло сообщение, иначе первый подключённый."""
    bots: list[dict[str, Any]] = []
    for name in connectors.names_of(conn, "telegram"):
        row = conn.execute(
            "SELECT config, state FROM connectors WHERE name = ?", (name,)
        ).fetchone()
        if row is not None and row["state"] == "ok":
            bots.append(json.loads(row["config"]))
    inbox = str(lead.get("inbox") or "").strip().lower()
    for config in bots:
        if inbox and f"@{config.get('bot_username') or ''}".lower() == inbox:
            return config
    return bots[0] if bots else None


def reply_info(conn: sqlite3.Connection, lead: Lead) -> dict[str, Any]:
    """Можно ли ответить из приложения и куда: показывается в карточке до отправки."""
    contact = str(lead.get("contact") or "").strip()
    channel = lead.get("channel")
    if channel == "telegram":
        reason = None
        if lead.get("category") == "spam":
            reason = "На спам не отвечаем."
        elif not lead.get("tg_chat_id"):
            reason = "Сообщение пришло не через бота — ответьте клиенту в Telegram вручную."
        elif _telegram_config(conn, lead) is None:
            reason = "Telegram-бот не подключён: «Почта и сервисы» → «Telegram-бот»."
        return {
            "available": reason is None,
            "reason": reason,
            "channel": "telegram",
            "to": contact or None,
            "from": "Telegram-бот",
            "subject": None,
        }
    reason = None
    if channel != "email":
        reason = "Ответ из приложения отправляется по почте и в Telegram."
    elif "@" not in contact:
        reason = "У обращения нет адреса электронной почты."
    elif lead.get("category") == "spam":
        reason = "На спам не отвечаем."
    elif _email_config(conn, lead) is None:
        reason = "Почта не подключена: «Почта и сервисы» → «Почта» → «Проверить связь»."
    config = _email_config(conn, lead) or {}
    return {
        "available": reason is None,
        "reason": reason,
        "channel": "email",
        "to": contact or None,
        "from": config.get("user"),
        "subject": _subject(lead),
    }


def sent_replies(conn: sqlite3.Connection, key: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT o.*, u.name AS user_name FROM outgoing o JOIN users u ON u.id = o.user_id "
        "WHERE o.lead_key = ? ORDER BY o.id",
        (key,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "to": row["recipient"],
            "subject": row["subject"],
            "body": row["body"],
            "status": row["status"],
            "error": row["error"],
            "user": row["user_name"],
            "at": row["created_at"],
        }
        for row in rows
    ]


def explain_smtp_error(exc: BaseException, host: str, port: int) -> str:
    """Понятная причина сбоя отправки и что сделать; техническая деталь — в скобках."""
    detail = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (
            "Почтовый сервер не принял логин или пароль. Для Mail.ru и Яндекса нужен "
            f"пароль для внешних приложений с доступом к SMTP. ({detail})"
        )
    if isinstance(exc, (ssl.SSLError, smtplib.SMTPServerDisconnected, ConnectionResetError)):
        return (
            f"Соединение с {host}:{port} обрывается сразу после подключения. Так обычно "
            "блокирует исходящую почту VPN или провайдер: добавьте приложение в исключения "
            "VPN или проверьте отправку на сервере. Чтение почты при этом работает. "
            f"({detail})"
        )
    if isinstance(exc, (TimeoutError, socket.timeout, ConnectionRefusedError, socket.gaierror)):
        return (
            f"Почтовый сервер {host}:{port} недоступен. Проверьте адрес SMTP-сервера в "
            f"«Подключениях» и доступ в интернет. ({detail})"
        )
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return f"Сервер отказался доставлять письмо на этот адрес. ({detail})"
    return f"Не удалось отправить письмо. ({detail})"


def _deliver(config: dict[str, Any], message: EmailMessage) -> None:
    host, port = smtp_endpoint(config)
    if port == 465:
        with smtplib.SMTP_SSL(
            host, port, timeout=TIMEOUT, context=ssl.create_default_context()
        ) as client:
            client.login(config["user"], config["password"])
            client.send_message(message)
        return
    with smtplib.SMTP(host, port, timeout=TIMEOUT) as client:
        if port == 587:
            client.starttls(context=ssl.create_default_context())
        if client.has_extn("auth"):
            client.login(config["user"], config["password"])
        client.send_message(message)


def send_reply(
    conn: sqlite3.Connection,
    lead: Lead,
    user_id: int,
    body: object,
    force: bool = False,
) -> dict[str, Any]:
    text = str(body or "").strip()
    if not text:
        raise OutboxError("INVALID_ARGUMENT", "Текст ответа пустой")
    if len(text) > MAX_BODY:
        raise OutboxError("INVALID_ARGUMENT", f"Ответ длиннее {MAX_BODY} символов")
    info = reply_info(conn, lead)
    if not info["available"]:
        raise OutboxError("NOT_AVAILABLE", str(info["reason"]))
    key = lead_key(lead["id"])
    already = conn.execute(
        "SELECT created_at FROM outgoing WHERE lead_key = ? AND status = 'sent' "
        "ORDER BY id DESC LIMIT 1",
        (key,),
    ).fetchone()
    if already and not force:
        raise OutboxError(
            "ALREADY_SENT", f"Ответ этому клиенту уже отправлен {already['created_at']}"
        )
    if info["channel"] == "telegram":
        message_id = None
        status, error = "sent", None
        try:
            message_id = _deliver_telegram(
                _telegram_config(conn, lead) or {}, int(lead["tg_chat_id"]), text
            )
        except (OSError, ValueError) as exc:
            status, error = "failed", explain_telegram_error(exc)
    else:
        config = _email_config(conn, lead) or {}
        message = EmailMessage()
        message["From"] = str(config["user"])
        message["To"] = str(info["to"])
        message["Subject"] = str(info["subject"])
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain=str(config["user"]).split("@")[-1])
        original = _original_message_id(lead)
        if original:
            message["In-Reply-To"] = original
            message["References"] = original
        message.set_content(text)
        message_id = message["Message-ID"]
        status, error = "sent", None
        try:
            _deliver(config, message)
        except (OSError, smtplib.SMTPException) as exc:
            status, error = "failed", explain_smtp_error(exc, *smtp_endpoint(config))
    with transaction(conn):
        conn.execute(
            "INSERT INTO outgoing(lead_key, channel, recipient, subject, body, status, error, "
            "message_id, user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                info["channel"],
                info["to"],
                info["subject"],
                text,
                status,
                error,
                message_id,
                user_id,
                utc_now(),
            ),
        )
        audit(conn, "reply_sent" if status == "sent" else "reply_failed", user_id, f"lead:{key}")
    if error:
        raise OutboxError("SEND_FAILED", error)
    return {"to": info["to"], "subject": info["subject"], "status": status}


def _deliver_telegram(config: dict[str, Any], chat_id: int, text: str) -> str:
    """Отправляет сообщение клиенту от имени бота; возвращает номер сообщения в Telegram."""
    request = urllib.request.Request(
        connectors.telegram_url(config, "sendMessage"),
        data=json.dumps({"chat_id": chat_id, "text": text}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "lead-assistant"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = json.loads(response.read() or b"{}")
    if not data.get("ok"):
        raise ValueError(str(data.get("description") or "Telegram не принял сообщение"))
    return str((data.get("result") or {}).get("message_id") or "")


def explain_telegram_error(exc: BaseException) -> str:
    detail = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, urllib.error.HTTPError):
        try:
            description = json.loads(exc.read() or b"{}").get("description", "")
        except ValueError:
            description = ""
        detail = f"HTTP {exc.code}: {description or exc.reason}"
        if exc.code == 403:
            return (
                f"Клиент заблокировал бота или удалил чат — ответить через бота нельзя. ({detail})"
            )
        if exc.code == 400 and "chat not found" in description.lower():
            return f"Чат с клиентом не найден: клиент должен сначала написать боту. ({detail})"
        if exc.code == 401:
            return f"Telegram не принял токен бота — проверьте его в «Почте и сервисах». ({detail})"
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        return (
            "Нет связи с Telegram (api.telegram.org). Проверьте интернет; в России Telegram "
            f"может быть доступен только через VPN. ({detail})"
        )
    return f"Не удалось отправить сообщение в Telegram. ({detail})"
