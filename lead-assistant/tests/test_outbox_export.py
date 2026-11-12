"""Ответ клиенту по почте и выгрузка списка писем в JSON/Excel/Word/PDF."""

from __future__ import annotations

import email
import io
import json
import socket
import socketserver
import threading
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from lead_assistant.storage import LeadStore
from lead_assistant.web import connectors, outbox
from lead_assistant.web.config import AppPaths
from lead_assistant.web.db import connect
from tests.web_helpers import PROCESSED, client_for, error_code, make_paths

INBOX = "leads@mail.example"


class _Smtp(socketserver.StreamRequestHandler):
    """Минимальный SMTP-сервер: принимает письма и складывает их в список."""

    received: list[bytes]

    def handle(self) -> None:
        self.wfile.write(b"220 test\r\n")
        while line := self.rfile.readline():
            command = line.strip().upper()
            if command.startswith((b"EHLO", b"HELO")):
                self.wfile.write(b"250 test\r\n")
            elif command == b"DATA":
                self.wfile.write(b"354 go\r\n")
                data = b""
                while (chunk := self.rfile.readline()) not in (b".\r\n", b""):
                    data += chunk
                self.received.append(data)
                self.wfile.write(b"250 queued\r\n")
            elif command == b"QUIT":
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                self.wfile.write(b"250 ok\r\n")


@contextmanager
def smtp_server() -> Iterator[tuple[int, list[bytes]]]:
    received: list[bytes] = []
    handler = type("Handler", (_Smtp,), {"received": received})
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address[1], received
    finally:
        server.shutdown()
        server.server_close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _mail_setup(tmp_path: Path, smtp_port: int) -> AppPaths:
    paths = make_paths(tmp_path, PROCESSED)
    LeadStore(paths.leads_file).append_leads(
        [
            {
                "date": "2026-11-12",
                "channel": "email",
                "name": "Ольга Петрова",
                "contact": "olga@client.example",
                "text": "Тема: Перевозка плитки\nНужно перевезти 12 тонн плитки.",
                "status": "new",
                "source_id": "email:<abc@client.example>",
                "inbox": INBOX,
            }
        ]
    )
    return paths


def _connect_mail(paths: AppPaths, smtp_port: int) -> None:
    conn = connect(paths.db_file)
    try:
        connectors.configure(
            conn,
            "email",
            {
                "host": "imap.mail.example",
                "user": INBOX,
                "password": "app-password",
                "smtp_host": "127.0.0.1",
                "smtp_port": str(smtp_port),
            },
            1,
        )
        conn.execute("UPDATE connectors SET state = 'ok' WHERE name = 'email'")
        conn.commit()
    finally:
        conn.close()


def test_smtp_endpoint_is_derived_from_imap_host() -> None:
    assert outbox.smtp_endpoint({"host": "imap.mail.ru"}) == ("smtp.mail.ru", 465)
    assert outbox.smtp_endpoint({"host": "x", "smtp_host": "s.example", "smtp_port": "587"}) == (
        "s.example",
        587,
    )


def test_reply_is_sent_in_thread_recorded_and_not_sent_twice(tmp_path: Path) -> None:
    with smtp_server() as (port, received):
        paths = _mail_setup(tmp_path, port)
        with client_for(paths) as client:
            key = str(client.get("/api/leads?source=" + INBOX).json()["leads"][0]["key"])
            before = client.get(f"/api/leads/{key}").json()
            # Пока почта не подключена — отправка недоступна, с понятной причиной.
            assert before["reply"]["available"] is False and "Почта не подключена" in str(
                before["reply"]["reason"]
            )
            _connect_mail(paths, port)
            detail = client.get(f"/api/leads/{key}").json()
            assert detail["reply"] == {
                "available": True,
                "reason": None,
                "to": "olga@client.example",
                "from": INBOX,
                "subject": "Re: Перевозка плитки",
            }
            text = "Здравствуйте, Ольга! Менеджер подготовит расчёт."
            sent = client.post(f"/api/leads/{key}/reply", json={"text": text})
            assert sent.status_code == 200, sent.text
            assert sent.json()["lead"]["replies"][0]["status"] == "sent"
            twice = client.post(f"/api/leads/{key}/reply", json={"text": text})
            assert twice.status_code == 409 and error_code(twice) == "ALREADY_SENT"
            forced = client.post(f"/api/leads/{key}/reply", json={"text": text, "force": True})
            assert forced.status_code == 200
    assert len(received) == 2
    message = email.message_from_bytes(received[0])
    assert message["To"] == "olga@client.example" and message["From"] == INBOX
    assert message["In-Reply-To"] == "<abc@client.example>"
    assert str(email.header.make_header(email.header.decode_header(message["Subject"]))) == (
        "Re: Перевозка плитки"
    )


def test_failed_delivery_is_reported_and_logged(tmp_path: Path) -> None:
    port = _free_port()  # на этом порту никто не слушает
    paths = _mail_setup(tmp_path, port)
    with client_for(paths) as client:
        _connect_mail(paths, port)
        key = str(client.get("/api/leads?source=" + INBOX).json()["leads"][0]["key"])
        failed = client.post(f"/api/leads/{key}/reply", json={"text": "Ответ"})
        assert failed.status_code == 502 and error_code(failed) == "SEND_FAILED"
        replies = client.get(f"/api/leads/{key}").json()["replies"]
        assert [r["status"] for r in replies] == ["failed"]
        empty = client.post(f"/api/leads/{key}/reply", json={"text": "  "})
        assert empty.status_code == 400


def test_reply_is_not_offered_for_telegram_or_spam(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, PROCESSED)
    with client_for(paths) as client:
        telegram = client.get("/api/leads/2").json()["reply"]
        assert telegram["available"] is False and "только по почте" in telegram["reason"]
        spam = client.get("/api/leads/3").json()["reply"]
        assert spam["available"] is False


def test_export_in_every_format_respects_filters(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, PROCESSED)
    with client_for(paths) as client:
        spam_ids = {lead["id"] for lead in client.get("/api/leads?category=spam").json()["leads"]}
        as_json = client.get("/api/leads/export?format=json&category=spam")
        assert as_json.status_code == 200
        assert "attachment" in as_json.headers["content-disposition"]
        assert {item["id"] for item in json.loads(as_json.content)} == spam_ids

        xlsx = client.get("/api/leads/export?format=xlsx")
        with zipfile.ZipFile(io.BytesIO(xlsx.content)) as book:
            sheet = book.read("xl/worksheets/sheet1.xml").decode("utf-8")
            assert "Текст обращения" in sheet and "Игорь" in sheet
            assert book.testzip() is None

        docx = client.get("/api/leads/export?format=docx&priority=high")
        with zipfile.ZipFile(io.BytesIO(docx.content)) as document:
            body = document.read("word/document.xml").decode("utf-8")
            assert "Почта — выгрузка" in body and "№ 9" in body

        pdf = client.get("/api/leads/export?format=pdf&category=complaint")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

        bad = client.get("/api/leads/export?format=csv")
        assert bad.status_code == 400
