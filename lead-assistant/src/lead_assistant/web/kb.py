"""Локальная база знаний: загрузка TXT/MD/PDF, полнотекстовый поиск, источники фрагментов.

Ограничения извлечения: только перечисленные типы, не больше ``MAX_BYTES``; PDF без
текстового слоя (скан) помечается «нужен OCR» и в поиск не попадает — OCR в этой
версии не подключён. Документ используется, только если он действует на текущую
дату и доступен роли пользователя.
"""

from __future__ import annotations

import hashlib
import io
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from lead_assistant.web.auth import ROLE_RANK, User
from lead_assistant.web.db import audit, transaction, utc_now

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 300
CHUNK_CHARS = 900
ALLOWED = {".txt": "text/plain", ".md": "text/markdown", ".pdf": "application/pdf"}
_WORD = re.compile(r"[0-9A-Za-zА-ЯЁа-яё]{4,}")
_STOP = {
    "здравствуйте",
    "добрый",
    "день",
    "пожалуйста",
    "подскажите",
    "спасибо",
    "можно",
    "нужно",
    "ваши",
    "ваше",
    "вашей",
    "есть",
    "какие",
    "когда",
    "сколько",
    "будет",
    "этой",
    "этот",
    "hello",
    "please",
    "thanks",
    "your",
    "with",
    "have",
    "need",
    "this",
    "that",
}


class KbError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Extracted:
    pages: list[str]
    status: str  # indexed | needs_ocr | empty


def extract_text(filename: str, data: bytes) -> Extracted:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED:
        raise KbError(
            "UNSUPPORTED_TYPE", f"Тип файла не поддерживается: {suffix or 'без расширения'}"
        )
    if len(data) > MAX_BYTES:
        raise KbError("TOO_LARGE", f"Файл больше {MAX_BYTES // 1024 // 1024} МБ")
    if suffix == ".pdf":
        if not data.startswith(b"%PDF"):
            raise KbError("BAD_FILE", "Файл не похож на PDF")
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data))
            if len(reader.pages) > MAX_PAGES:
                raise KbError("TOO_LARGE", f"В PDF больше {MAX_PAGES} страниц")
            pages = [(page.extract_text() or "").strip() for page in reader.pages]
        except PdfReadError as error:
            raise KbError("BAD_FILE", f"PDF не читается: {error}") from error
        if not any(pages):
            # Страницы есть, текста нет — это скан: нужен OCR.
            return Extracted(pages=[], status="needs_ocr")
        return Extracted(pages=pages, status="indexed")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1251")
        except UnicodeDecodeError as error:
            raise KbError("BAD_ENCODING", "Текст должен быть в UTF-8 или Windows-1251") from error
    text = text.strip()
    return Extracted(pages=[text] if text else [], status="indexed" if text else "empty")


def chunk_pages(pages: list[str]) -> list[tuple[int | None, str]]:
    chunks: list[tuple[int | None, str]] = []
    single = len(pages) == 1
    for number, page in enumerate(pages, start=1):
        buffer = ""
        for paragraph in re.split(r"\n\s*\n", page):
            paragraph = " ".join(paragraph.split())
            if not paragraph:
                continue
            if buffer and len(buffer) + len(paragraph) > CHUNK_CHARS:
                chunks.append((None if single else number, buffer))
                buffer = ""
            buffer = f"{buffer}\n{paragraph}".strip()
            while len(buffer) > CHUNK_CHARS * 1.5:
                chunks.append((None if single else number, buffer[:CHUNK_CHARS]))
                buffer = buffer[CHUNK_CHARS:]
        if buffer:
            chunks.append((None if single else number, buffer))
    return chunks


def add_document(
    conn: sqlite3.Connection,
    uploads: Path,
    user: User,
    filename: str,
    data: bytes,
    title: str,
    version: str,
    owner: str,
    valid_from: str | None,
    valid_to: str | None,
    min_role: str = "manager",
) -> dict[str, Any]:
    if not title.strip() or not version.strip() or not owner.strip():
        raise KbError("INVALID_ARGUMENT", "Нужны название, версия и ответственный")
    if min_role not in ROLE_RANK:
        raise KbError("INVALID_ARGUMENT", "Неизвестная роль доступа")
    for value in (valid_from, valid_to):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError as error:
                raise KbError("INVALID_ARGUMENT", "Даты действия — в формате ГГГГ-ММ-ДД") from error
    extracted = extract_text(filename, data)
    digest = hashlib.sha256(data).hexdigest()
    suffix = Path(filename).suffix.lower()
    safe_name = f"{digest[:16]}{suffix}"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / safe_name).write_bytes(data)
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO documents(title, version, valid_from, valid_to, owner, filename, "
            "media_type, sha256, size_bytes, status, min_role, uploaded_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                title.strip(),
                version.strip(),
                valid_from or None,
                valid_to or None,
                owner.strip(),
                Path(filename).name,
                ALLOWED[suffix],
                digest,
                len(data),
                extracted.status,
                min_role,
                user.id,
                utc_now(),
            ),
        )
        doc_id = cursor.lastrowid
        for ordinal, (page, text) in enumerate(chunk_pages(extracted.pages)):
            conn.execute(
                "INSERT INTO chunks(document_id, ordinal, page, text) VALUES (?, ?, ?, ?)",
                (doc_id, ordinal, page, text),
            )
        audit(conn, "kb_document_added", user.id, f"document:{doc_id}", status=extracted.status)
    assert doc_id is not None
    return get_document(conn, doc_id, user)


def _doc(row: sqlite3.Row, today: str) -> dict[str, Any]:
    current = (row["valid_from"] or "0000") <= today and today <= (row["valid_to"] or "9999")
    return {
        "id": row["id"],
        "title": row["title"],
        "version": row["version"],
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
        "owner": row["owner"],
        "filename": row["filename"],
        "size_bytes": row["size_bytes"],
        "status": row["status"],
        "min_role": row["min_role"],
        "current": current,
        "created_at": row["created_at"],
    }


def _allowed_roles(user: User) -> list[str]:
    return [role for role, rank in ROLE_RANK.items() if rank <= ROLE_RANK[user.role]]


def list_documents(conn: sqlite3.Connection, user: User) -> list[dict[str, Any]]:
    roles = _allowed_roles(user)
    marks = ",".join("?" * len(roles))
    rows = conn.execute(
        f"SELECT * FROM documents WHERE min_role IN ({marks}) ORDER BY title, created_at DESC",
        roles,
    ).fetchall()
    today = date.today().isoformat()
    docs = [_doc(row, today) for row in rows]
    titles: dict[str, int] = {}
    for doc in docs:
        if doc["current"] and doc["status"] == "indexed":
            titles[doc["title"].lower()] = titles.get(doc["title"].lower(), 0) + 1
    for doc in docs:
        doc["conflict"] = doc["current"] and titles.get(doc["title"].lower(), 0) > 1
    return docs


def get_document(conn: sqlite3.Connection, doc_id: int, user: User) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if row is None or ROLE_RANK[row["min_role"]] > ROLE_RANK[user.role]:
        raise KbError("NOT_FOUND", "Документ не найден")
    return _doc(row, date.today().isoformat())


def _fts_query(text: str) -> str | None:
    words = []
    for word in _WORD.findall(text.lower()):
        if word in _STOP or word.isdigit():
            continue
        stem = word[: max(4, len(word) - 2)]  # грубая основа для русских окончаний
        token = f'"{stem}"*'
        if token not in words:
            words.append(token)
    return " OR ".join(words[:24]) or None


def search(conn: sqlite3.Connection, user: User, text: str, limit: int = 5) -> dict[str, Any]:
    """Ищет фрагменты в действующих документах, доступных роли пользователя."""
    query = _fts_query(text)
    if query is None:
        return {"results": [], "conflicts": []}
    roles = _allowed_roles(user)
    marks = ",".join("?" * len(roles))
    today = date.today().isoformat()
    rows = conn.execute(
        "SELECT c.id AS chunk_id, c.page, c.text, d.*, bm25(chunks_fts) AS score "
        "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
        "JOIN documents d ON d.id = c.document_id "
        f"WHERE chunks_fts MATCH ? AND d.status = 'indexed' AND d.min_role IN ({marks}) "
        "AND COALESCE(d.valid_from, '0000') <= ? AND COALESCE(d.valid_to, '9999') >= ? "
        "ORDER BY score LIMIT ?",
        (query, *roles, today, today, limit * 4),
    ).fetchall()
    results: list[dict[str, Any]] = []
    seen_documents: set[int] = set()
    for row in rows:
        # Из каждого документа — один, самый подходящий фрагмент: так в выдаче разные источники.
        if row["id"] in seen_documents:
            continue
        seen_documents.add(row["id"])
        if len(results) >= limit:
            break
        results.append(
            {
                "chunk_id": row["chunk_id"],
                "page": row["page"],
                "fragment": row["text"][:600],
                "document": _doc(row, today),
                "source": f"{row['title']}, версия {row['version']}"
                + (f", стр. {row['page']}" if row["page"] else ""),
            }
        )
    by_title: dict[str, set[str]] = {}
    for item in results:
        by_title.setdefault(item["document"]["title"].lower(), set()).add(
            item["document"]["version"]
        )
    conflicts = [
        f"Найдены фрагменты из разных версий документа «{title}»: {', '.join(sorted(versions))}"
        for title, versions in by_title.items()
        if len(versions) > 1
    ]
    return {"results": results, "conflicts": conflicts}


def get_chunk(conn: sqlite3.Connection, user: User, chunk_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT c.id AS chunk_id, c.page, c.text, c.ordinal, d.* FROM chunks c "
        "JOIN documents d ON d.id = c.document_id WHERE c.id = ?",
        (chunk_id,),
    ).fetchone()
    if row is None or ROLE_RANK[row["min_role"]] > ROLE_RANK[user.role]:
        raise KbError("NOT_FOUND", "Фрагмент не найден")
    return {
        "chunk_id": row["chunk_id"],
        "page": row["page"],
        "ordinal": row["ordinal"],
        "text": row["text"],
        "document": _doc(row, date.today().isoformat()),
    }


def delete_document(conn: sqlite3.Connection, user: User, doc_id: int) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        if not conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,)).rowcount:
            raise KbError("NOT_FOUND", "Документ не найден")
        audit(conn, "kb_document_deleted", user.id, f"document:{doc_id}")
