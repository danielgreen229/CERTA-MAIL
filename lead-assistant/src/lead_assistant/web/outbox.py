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
import sqlite3
import ssl
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
    topic = first[len("Тема: ") :].strip() if first.startswith("Тема: ") else ""
    if not topic:
        return "Re: ваше обращение"
    return topic if topic.lower().startswith("re:") else f"Re: {topic}"


def _original_message_id(lead: Lead) -> str | None:
    channel, _, external = str(lead.get("source_id") or "").partition(":")
    if not connectors.is_mailbox(channel):
        return None
    return external or None


def reply_info(conn: sqlite3.Connection, lead: Lead) -> dict[str, Any]:
    """Можно ли ответить из приложения и куда: показывается в карточке до отправки."""
    contact = str(lead.get("contact") or "").strip()
    reason = None
    if lead.get("channel") != "email":
        reason = "Ответ из приложения пока отправляется только по почте."
    elif "@" not in contact:
        reason = "У обращения нет адреса электронной почты."
    elif lead.get("category") == "spam":
        reason = "На спам не отвечаем."
    elif _email_config(conn, lead) is None:
        reason = "Почта не подключена: «Подключения» → «Почта» → «Проверить»."
    config = _email_config(conn, lead) or {}
    return {
        "available": reason is None,
        "reason": reason,
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
    status, error = "sent", None
    try:
        _deliver(config, message)
    except (OSError, smtplib.SMTPException) as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"
    with transaction(conn):
        conn.execute(
            "INSERT INTO outgoing(lead_key, channel, recipient, subject, body, status, error, "
            "message_id, user_id, created_at) VALUES (?, 'email', ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                info["to"],
                info["subject"],
                text,
                status,
                error,
                message["Message-ID"],
                user_id,
                utc_now(),
            ),
        )
        audit(conn, "reply_sent" if status == "sent" else "reply_failed", user_id, f"lead:{key}")
    if error:
        raise OutboxError("SEND_FAILED", f"Не удалось отправить: {error}")
    return {"to": info["to"], "subject": info["subject"], "status": status}
