"""База знаний и подключения: ограничения, права, актуальность, тестовый сервис, импорт."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from lead_assistant.storage import LeadStore
from lead_assistant.web import connectors, kb, mockservice
from lead_assistant.web.auth import User
from lead_assistant.web.db import connect, init_db
from tests.web_helpers import client_for, make_paths

ADMIN = User(1, "admin", "Админ", "admin", False)
MANAGER = User(2, "m", "Менеджер", "manager", False)


def text_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def scanned_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.fixture
def conn(tmp_path: Path):  # type: ignore[no-untyped-def]
    path = tmp_path / "app.db"
    init_db(path)
    connection = connect(path)
    connection.execute(
        "INSERT INTO users(id, login, name, role, password_hash, created_at) VALUES "
        "(1, 'admin', 'Админ', 'admin', 'x', 'now'), (2, 'm', 'Менеджер', 'manager', 'x', 'now')"
    )
    yield connection
    connection.close()


def add(conn, tmp_path: Path, name: str, data: bytes, **kw: str):  # type: ignore[no-untyped-def]
    params = {
        "title": "Условия",
        "version": "1",
        "owner": "Юрист",
        "valid_from": None,
        "valid_to": None,
        "min_role": "manager",
        **kw,
    }
    return kb.add_document(
        conn,
        tmp_path / "up",
        ADMIN,
        name,
        data,
        str(params["title"]),
        str(params["version"]),
        str(params["owner"]),
        params["valid_from"],
        params["valid_to"],
        str(params["min_role"]),
    )


def test_text_and_pdf_are_indexed_and_scans_need_ocr(conn, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    text = (
        "Работаем с юрлицами по договору с отсрочкой платежа до 30 дней.\n\n"
        "Доставка в Казань — 3 дня."
    )
    doc = add(conn, tmp_path, "условия.txt", text.encode("utf-8"))
    assert doc["status"] == "indexed"
    pdf = add(
        conn, tmp_path, "tariff.pdf", text_pdf("Tariff Kazan 5000 RUB per pallet"), title="Tariffs"
    )
    assert pdf["status"] == "indexed"
    scan = add(conn, tmp_path, "scan.pdf", scanned_pdf(), title="Скан")
    assert scan["status"] == "needs_ocr"
    found = kb.search(conn, MANAGER, "Работаете ли вы с юрлицами с отсрочкой платежа?")
    assert found["results"][0]["document"]["title"] == "Условия"
    assert "отсрочкой" in found["results"][0]["fragment"]
    chunk = kb.get_chunk(conn, MANAGER, found["results"][0]["chunk_id"])
    assert chunk["document"]["owner"] == "Юрист"
    assert kb.search(conn, MANAGER, "tariff pallet")["results"][0]["document"]["title"] == "Tariffs"


def test_limits_on_type_and_size(conn, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(kb.KbError) as wrong:
        add(conn, tmp_path, "virus.exe", b"MZ")
    assert wrong.value.code == "UNSUPPORTED_TYPE"
    with pytest.raises(kb.KbError) as big:
        add(conn, tmp_path, "big.txt", b"a" * (kb.MAX_BYTES + 1))
    assert big.value.code == "TOO_LARGE"
    with pytest.raises(kb.KbError) as fake:
        add(conn, tmp_path, "fake.pdf", b"not a pdf")
    assert fake.value.code == "BAD_FILE"


def test_rights_and_validity_are_respected(conn, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    add(
        conn,
        tmp_path,
        "secret.txt",
        "Внутренняя наценка на перевозку".encode(),
        title="Наценки",
        min_role="supervisor",
    )
    add(
        conn,
        tmp_path,
        "old.txt",
        "Перевозка рефрижератором устарела".encode(),
        title="Старый",
        valid_to="2020-01-01",
    )
    assert kb.search(conn, MANAGER, "наценка перевозку")["results"] == []
    assert kb.search(conn, ADMIN, "наценка")["results"]
    assert kb.search(conn, ADMIN, "рефрижератором")["results"] == []
    assert not any(doc["title"] == "Наценки" for doc in kb.list_documents(conn, MANAGER))


def test_conflicting_versions_are_flagged(conn, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    add(conn, tmp_path, "a.txt", "Отсрочка платежа 30 дней".encode(), title="Условия", version="1")
    add(conn, tmp_path, "b.txt", "Отсрочка платежа 14 дней".encode(), title="Условия", version="2")
    found = kb.search(conn, MANAGER, "отсрочка платежа")
    assert found["conflicts"] and "1, 2" in found["conflicts"][0]
    assert all(doc["conflict"] for doc in kb.list_documents(conn, MANAGER))


def test_test_service_contract_status_and_telegram_import_without_duplicates(
    tmp_path: Path,
) -> None:
    server, base = mockservice.start()
    try:
        paths = make_paths(tmp_path)
        with client_for(paths, "admin") as client:
            assert (
                client.get("/api/connectors").json()["connectors"][0]["state"] == "not_configured"
            )
            client.put("/api/connectors/tms", json={"base_url": base, "test_service": True})
            checked = client.post("/api/connectors/tms/check").json()
            assert checked["state"] == "ok" and checked["detail"].startswith("ТЕСТОВЫЙ СЕРВИС")
            conn = connect(paths.db_file)
            status = connectors.shipment_status(conn, "77812")
            conn.close()
            assert status is not None and status["data"]["status"] == "в пути"
            assert status["source"].startswith("ТЕСТОВЫЙ СЕРВИС") and status["fetched_at"]

            client.put(
                "/api/connectors/telegram",
                json={"bot_token": mockservice.TOKEN, "api_base": base, "test_service": True},
            )
            listed = client.get("/api/connectors").json()["connectors"]
            telegram = next(c for c in listed if c["name"] == "telegram")
            assert telegram["config"]["bot_token"] == "••••••", "секрет не отдаётся обратно"
            assert client.post("/api/connectors/telegram/check").json()["state"] == "ok"
            first = client.post("/api/connectors/telegram/import").json()
            again = client.post("/api/connectors/telegram/import").json()
            assert first["imported"] == 1 and again == {"imported": 0, "skipped": 1, "ids": []}
        leads = LeadStore(paths.leads_file).snapshot().leads
        imported = leads[-1]
        assert imported["id"] == 16 and imported["status"] == "new"
        assert imported["channel"] == "telegram" and imported["source_id"] == "telegram:9001"
    finally:
        server.shutdown()


def test_import_is_not_duplicated_after_crash_between_file_and_db(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    store = LeadStore(paths.leads_file)
    # Падение после записи в файл, но до записи в SQLite: в файле уже есть source_id.
    store.append_leads(
        [
            {
                "date": "2026-11-12",
                "channel": "telegram",
                "name": "Т",
                "contact": "@t",
                "text": "привет",
                "source_id": "telegram:9001",
            }
        ]
    )
    init_db(paths.db_file)
    conn = connect(paths.db_file)
    conn.execute(
        "INSERT INTO users(id, login, name, role, password_hash, created_at) "
        "VALUES (1, 'a', 'A', 'admin', 'x', 'now')"
    )
    item = connectors.normalize_telegram(mockservice.UPDATES[0])
    assert item is not None
    result = connectors._store_imported(conn, store, "telegram", [item], 1)
    conn.close()
    assert result["imported"] == 0 and result["skipped"] == 1
    assert (
        sum(1 for lead in store.snapshot().leads if lead.get("source_id") == "telegram:9001") == 1
    )


def test_email_is_normalized() -> None:
    raw = (
        "From: =?utf-8?b?0JjQstCw0L0g0J/QtdGC0YDQvtCy?= <ivan@example.com>\r\n"
        "Subject: Перевозка\r\nMessage-ID: <abc@example.com>\r\n"
        "Date: Tue, 10 Nov 2026 10:00:00 +0300\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\nНужно перевезти 3 паллеты."
    ).encode()
    item = connectors.normalize_email(raw)
    assert item["external_id"] == "<abc@example.com>"
    assert item["lead"] == {
        "date": "2026-11-10",
        "channel": "email",
        "name": "Иван Петров",
        "contact": "ivan@example.com",
        "text": "Тема: Перевозка\nНужно перевезти 3 паллеты.",
    }
    assert json.dumps(item, ensure_ascii=False)


def test_html_only_email_keeps_body_and_subject_with_facts() -> None:
    raw = (
        "From: promo@example.com\r\nSubject: Груз повреждён — накладная 55120\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        "<style>p{color:red}</style><p>Две паллеты <b>разбиты</b>.</p><p>Акт не подписан.</p>"
    ).encode()
    text = connectors.normalize_email(raw)["lead"]["text"]
    assert text == "Тема: Груз повреждён — накладная 55120\nДве паллеты разбиты.\nАкт не подписан."


def test_env_presets_configure_and_check_but_never_override_admin(tmp_path: Path) -> None:
    server, base = mockservice.start()
    path = tmp_path / "app.db"
    init_db(path)
    conn = connect(path)
    try:
        env = {
            "LEADS_TMS_BASE_URL": base,
            "LEADS_TMS_STATUS_PATH": "/shipments/{number}",
            "LEADS_EMAIL_HOST": "imap.example.test",
            "LEADS_EMAIL_USER": "box@example.test",
            "LEADS_EMAIL_PASSWORD": "  ",  # пустой пароль не считается заданным
            "OTHER": "x",
        }
        assert connectors.env_presets(env) == {
            "tms": {"base_url": base, "status_path": "/shipments/{number}"},
            "email": {"host": "imap.example.test", "user": "box@example.test"},
        }
        applied = connectors.apply_env_presets(conn, env, 1)
        # TMS настроен и сразу проверен; почте не хватает пароля — ждёт администратора.
        assert applied == {"tms": "ok", "email": "not_configured"}
        email = next(c for c in connectors.list_connectors(conn) if c["name"] == "email")
        assert email["config"]["user"] == "box@example.test"
        connectors.configure(conn, "tms", {"base_url": "http://admin.example.test"}, 1)
        assert connectors.apply_env_presets(conn, env, 1) == {"email": "not_configured"}
        tms = next(c for c in connectors.list_connectors(conn) if c["name"] == "tms")
        assert tms["config"]["base_url"] == "http://admin.example.test"
    finally:
        conn.close()
        server.shutdown()


def test_imap_folder_names_are_encoded_like_mail_ru_lists_them() -> None:
    # Ожидаемые значения взяты из списка папок реального ящика Mail.ru.
    assert connectors.imap_folder("Заявки") == "&BBcEMARPBDIEOgQ4-"
    assert connectors.imap_folder("Отправленные") == "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-"
    assert connectors.imap_folder("INBOX") == "INBOX"
    assert connectors.imap_folder("INBOX/Public services") == "INBOX/Public services"
    assert connectors.imap_folder("R&D Заявки") == "R&-D &BBcEMARPBDIEOgQ4-"
    # Уже закодированное имя (скопировано из списка папок) не кодируется повторно.
    assert connectors.imap_folder("&BBcEMARPBDIEOgQ4-") == "&BBcEMARPBDIEOgQ4-"
