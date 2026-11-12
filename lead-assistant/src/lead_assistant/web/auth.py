"""Пользователи, пароли, сессии входа и проверка ролей."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lead_assistant.web.db import audit, transaction, utc_now

ROLES: tuple[str, ...] = ("manager", "supervisor", "admin")
ROLE_RANK = {role: rank for rank, role in enumerate(ROLES)}
SESSION_DAYS = 7
_ITERATIONS = 310_000
MIN_PASSWORD = 10


class AuthError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class User:
    id: int
    login: str
    name: str
    role: str
    must_change_password: bool

    def has_role(self, minimum: str) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[minimum]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "login": self.login,
            "name": self.name,
            "role": self.role,
            "must_change_password": self.must_change_password,
        }


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def _row_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        login=row["login"],
        name=row["name"],
        role=row["role"],
        must_change_password=bool(row["must_change_password"]),
    )


def check_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError("WEAK_PASSWORD", f"Пароль должен быть не короче {MIN_PASSWORD} символов")


def create_user(
    conn: sqlite3.Connection,
    login: str,
    name: str,
    role: str,
    password: str,
    must_change: bool = True,
    actor: int | None = None,
) -> User:
    if role not in ROLES:
        raise AuthError("INVALID_ROLE", f"Неизвестная роль: {role}")
    login = login.strip().lower()
    if not login or not name.strip():
        raise AuthError("INVALID_ARGUMENT", "Нужны логин и имя")
    check_password_strength(password)
    with transaction(conn):
        if conn.execute("SELECT 1 FROM users WHERE login = ?", (login,)).fetchone():
            raise AuthError("USER_EXISTS", f"Пользователь {login} уже есть")
        cursor = conn.execute(
            "INSERT INTO users(login, name, role, password_hash, must_change_password, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (login, name.strip(), role, hash_password(password), int(must_change), utc_now()),
        )
        audit(conn, "user_created", actor, f"user:{cursor.lastrowid}", login=login, role=role)
    user_id = cursor.lastrowid
    assert user_id is not None
    return get_user(conn, user_id)


def get_user(conn: sqlite3.Connection, user_id: int) -> User:
    row = conn.execute("SELECT * FROM users WHERE id = ? AND active = 1", (user_id,)).fetchone()
    if row is None:
        raise AuthError("NOT_FOUND", "Пользователь не найден")
    return _row_user(row)


def list_users(conn: sqlite3.Connection) -> list[User]:
    rows = conn.execute("SELECT * FROM users WHERE active = 1 ORDER BY id").fetchall()
    return [_row_user(row) for row in rows]


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def login(conn: sqlite3.Connection, login_name: str, password: str) -> tuple[User, str]:
    row = conn.execute(
        "SELECT * FROM users WHERE login = ? AND active = 1", (login_name.strip().lower(),)
    ).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        audit(conn, "login_failed", None, None, login=login_name[:64])
        raise AuthError("BAD_CREDENTIALS", "Неверный логин или пароль")
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=SESSION_DAYS)
    with transaction(conn):
        conn.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (_token_hash(token), row["id"], utc_now(), expires.isoformat()),
        )
        audit(conn, "login", row["id"], f"user:{row['id']}")
    return _row_user(row), token


def logout(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def user_by_token(conn: sqlite3.Connection, token: str | None) -> User | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT u.*, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND u.active = 1",
        (_token_hash(token),),
    ).fetchone()
    if row is None:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(UTC):
        logout(conn, token)
        return None
    return _row_user(row)


def change_password(conn: sqlite3.Connection, user: User, old: str, new: str) -> None:
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()
    if row is None or not verify_password(old, row["password_hash"]):
        raise AuthError("BAD_CREDENTIALS", "Текущий пароль указан неверно")
    check_password_strength(new)
    if old == new:
        raise AuthError("WEAK_PASSWORD", "Новый пароль должен отличаться от текущего")
    with transaction(conn):
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
            (hash_password(new), user.id),
        )
        audit(conn, "password_changed", user.id, f"user:{user.id}")


def bootstrap_admin(conn: sqlite3.Connection, secret_file: Path) -> str | None:
    """Создаёт локального администратора при первом запуске.

    Начальный пароль случайный, хранится только хешем; открытым текстом он один раз
    записывается в файл с правами только для владельца и выводится в консоль.
    При первом входе пароль нужно сменить. Возвращает пароль или None, если
    пользователи уже есть.
    """
    if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        return None
    password = secrets.token_urlsafe(12)
    create_user(conn, "admin", "Администратор", "admin", password, must_change=True)
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(
        "Первоначальный вход в рабочее место менеджера\n"
        f"логин: admin\nпароль: {password}\n"
        "Пароль нужно сменить при первом входе; после этого удалите этот файл.\n",
        encoding="utf-8",
    )
    secret_file.chmod(0o600)
    return password
