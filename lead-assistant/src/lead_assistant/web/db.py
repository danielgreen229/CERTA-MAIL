"""Служебная база SQLite: схема, подключение, настройки, аудит."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lead_assistant.web.config import DEFAULT_SETTINGS

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('manager', 'supervisor', 'admin')),
    password_hash TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- Задача фоновой обработки. Одновременно активна не более одной (частичный индекс).
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'done', 'failed', 'cancelled')),
    requested_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    heartbeat_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    params TEXT NOT NULL DEFAULT '{}',
    progress TEXT NOT NULL DEFAULT '{}',
    run_ids TEXT NOT NULL DEFAULT '[]',
    summary TEXT,
    error TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_one_active
    ON jobs(kind) WHERE state IN ('queued', 'running');

-- Версии результата AI-обработки: снимок полей из leads.json и разбор прогона.
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY,
    lead_key TEXT NOT NULL,
    version INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    category TEXT,
    priority TEXT,
    draft_reply TEXT,
    analysis TEXT NOT NULL DEFAULT '{}',
    run_id TEXT,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (lead_key, version),
    UNIQUE (lead_key, content_hash)
);

-- Решение менеджера относится к конкретной версии результата.
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY,
    lead_key TEXT NOT NULL,
    result_id INTEGER NOT NULL REFERENCES results(id),
    action TEXT NOT NULL CHECK (action IN ('accept', 'correct', 'reject')),
    category TEXT,
    priority TEXT,
    draft_reply TEXT,
    reason TEXT,
    changes TEXT NOT NULL DEFAULT '{}',
    previous_decision_id INTEGER REFERENCES decisions(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decisions_lead ON decisions(lead_key, id);

CREATE TABLE IF NOT EXISTS assignments (
    lead_key TEXT PRIMARY KEY,
    assignee TEXT,
    due_at TEXT,
    set_by INTEGER REFERENCES users(id),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    user_id INTEGER,
    action TEXT NOT NULL,
    target TEXT,
    details TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    owner TEXT NOT NULL,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('indexed', 'needs_ocr', 'empty')),
    min_role TEXT NOT NULL DEFAULT 'manager',
    uploaded_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    page INTEGER,
    text TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TABLE IF NOT EXISTS connectors (
    name TEXT PRIMARY KEY,
    config TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL DEFAULT 'not_configured',
    checked_at TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS imported_messages (
    channel TEXT NOT NULL,
    external_id TEXT NOT NULL,
    lead_id TEXT,
    imported_at TEXT NOT NULL,
    PRIMARY KEY (channel, external_id)
);
CREATE TABLE IF NOT EXISTS outgoing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_key TEXT NOT NULL,
    channel TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT,
    body TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    message_id TEXT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS outgoing_lead ON outgoing(lead_key, id);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def lead_key(lead_id: object) -> str:
    """Ключ заявки в SQLite сохраняет тип ID: 1 и "1" — разные заявки."""
    return json.dumps(lead_id, ensure_ascii=False)


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def audit(
    conn: sqlite3.Connection,
    action: str,
    user_id: int | None = None,
    target: str | None = None,
    **details: Any,
) -> None:
    conn.execute(
        "INSERT INTO audit(ts, user_id, action, target, details) VALUES (?, ?, ?, ?, ?)",
        (utc_now(), user_id, action, target, json.dumps(details, ensure_ascii=False)),
    )


def get_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    settings: dict[str, Any] = json.loads(json.dumps(DEFAULT_SETTINGS))
    for row in conn.execute("SELECT key, value FROM settings"):
        settings[row["key"]] = json.loads(row["value"])
    return settings


def put_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )
