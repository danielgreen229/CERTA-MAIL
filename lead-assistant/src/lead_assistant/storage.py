"""Хранилище заявок в JSON-файле.

Гарантии:
* структура, порядок заявок и все поля вне EDITABLE_FIELDS сохраняются;
* запись идёт под блокировкой отдельного lock-файла: под ней файл перечитывается,
  проверяется статус заявки, затем данные атомарно заменяются через временный файл
  в том же каталоге (fsync файла, os.replace, fsync каталога);
* исходы различаются: «записано», «повтор с теми же значениями» (файл не меняется),
  «конфликт» (файл не меняется) и ошибки с кодом.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import sys
import tempfile
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from lead_assistant.locking import exclusive_lock
from lead_assistant.models import (
    EDITABLE_FIELDS,
    STATUS_NEW,
    STATUS_PROCESSED,
    ErrorCode,
    LeadError,
    LeadId,
    is_valid_lead_id,
    validate_update,
)

type Lead = dict[str, Any]
type Layout = Literal["lines", "indent2", "indent4", "compact"]

DEFAULT_LOCK_TIMEOUT_SECONDS = 10.0
_BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True)
class FileStyle:
    """Оформление исходного файла, чтобы запись не меняла нетронутые строки."""

    layout: Layout = "indent2"
    ensure_ascii: bool = False
    newline: str = "\n"
    trailing_newline: bool = True
    bom: bool = False


@dataclass(frozen=True)
class Snapshot:
    """Согласованное состояние файла на момент чтения."""

    leads: list[Lead]
    sha256: str
    style: FileStyle


@dataclass(frozen=True)
class UpdateResult:
    """Исход update_lead, не являющийся ошибкой."""

    lead_id: LeadId
    result: Literal["updated", "unchanged"]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LeadError(
                ErrorCode.STORAGE_INVALID,
                f"an object repeats the key {key!r}; refusing to drop data silently",
            )
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-standard JSON constant {name}")


def parse_leads(raw: bytes) -> list[Lead]:
    """Разбирает и проверяет содержимое файла. Ошибки имеют понятные коды."""
    body = raw[len(_BOM) :] if raw.startswith(_BOM) else raw
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LeadError(ErrorCode.STORAGE_CORRUPT, f"file is not valid UTF-8: {exc}") from exc
    try:
        data = json.loads(
            text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant
        )
    except json.JSONDecodeError as exc:
        raise LeadError(
            ErrorCode.STORAGE_CORRUPT,
            f"file is not valid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}",
            line=exc.lineno,
            column=exc.colno,
        ) from exc
    except ValueError as exc:
        raise LeadError(ErrorCode.STORAGE_CORRUPT, f"file is not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise LeadError(
            ErrorCode.STORAGE_INVALID,
            f"expected a JSON array of leads at the top level, got {type(data).__name__}",
        )

    seen: dict[str, int] = {}
    duplicates: list[Any] = []
    for index, lead in enumerate(data):
        if not isinstance(lead, dict):
            raise LeadError(
                ErrorCode.STORAGE_INVALID,
                f"lead at position {index} is not an object",
                position=index,
            )
        lead_id = lead.get("id")
        if not is_valid_lead_id(lead_id):
            raise LeadError(
                ErrorCode.STORAGE_INVALID,
                f"lead at position {index} has no valid 'id' (integer or non-empty string)",
                position=index,
            )
        if not isinstance(lead.get("status"), str):
            raise LeadError(
                ErrorCode.STORAGE_INVALID,
                f"lead {lead_id!r} at position {index} has no string 'status'",
                position=index,
            )
        # 1 и "1" считаются одним ID: иначе модель легко перепутает записи.
        key = str(lead_id)
        if key in seen:
            duplicates.append(lead["id"])
        seen[key] = index
    if duplicates:
        raise LeadError(
            ErrorCode.DUPLICATE_ID,
            f"duplicate lead IDs in the file: {duplicates!r}; fix the data before processing",
            ids=duplicates,
        )
    return data


def _dump(value: Any, style: FileStyle, indent: int | None = None) -> str:
    return json.dumps(value, ensure_ascii=style.ensure_ascii, indent=indent)


def serialize_leads(leads: list[Lead], style: FileStyle) -> bytes:
    """Сериализует заявки в оформлении исходного файла."""
    if style.layout == "lines":
        if leads:
            rows = ",\n".join("  " + _dump(lead, style) for lead in leads)
            text = f"[\n{rows}\n]"
        else:
            text = "[]"
    elif style.layout == "compact":
        text = _dump(leads, style)
    else:
        text = _dump(leads, style, indent=2 if style.layout == "indent2" else 4)
    if style.trailing_newline:
        text += "\n"
    if style.newline != "\n":
        text = text.replace("\n", style.newline)
    data = text.encode("utf-8")
    return _BOM + data if style.bom else data


def detect_style(raw: bytes, leads: list[Lead]) -> FileStyle:
    """Подбирает оформление, при котором сериализация воспроизводит файл байт в байт."""
    bom = raw.startswith(_BOM)
    newline = "\r\n" if b"\r\n" in raw else "\n"
    trailing = raw.endswith(b"\n")
    layouts: tuple[Layout, ...] = ("lines", "indent2", "indent4", "compact")
    for layout in layouts:
        for ensure_ascii in (False, True):
            style = FileStyle(layout, ensure_ascii, newline, trailing, bom)
            if serialize_leads(leads, style) == raw:
                return style
    # Оформление не распознано: файл будет нормализован при первой записи.
    return FileStyle("indent2", False, newline, True, bom)


def find_lead(leads: list[Lead], lead_id: LeadId) -> Lead:
    """Ищет заявку с точным совпадением значения и типа ID."""
    for lead in leads:
        candidate = lead["id"]
        if type(candidate) is type(lead_id) and candidate == lead_id:
            return lead
    hint = None
    for lead in leads:
        if str(lead["id"]) == str(lead_id):
            hint = (
                f"a lead with id {lead['id']!r} ({type(lead['id']).__name__}) exists; "
                "pass the id exactly as list_leads returned it"
            )
            break
    details: dict[str, Any] = {"id": lead_id}
    if hint:
        details["hint"] = hint
    raise LeadError(
        ErrorCode.NOT_FOUND,
        f"lead with id {lead_id!r} ({type(lead_id).__name__}) does not exist"
        + (f"; {hint}" if hint else ""),
        **details,
    )


class LeadStore:
    """Доступ к файлу заявок. Экземпляр не хранит состояние между вызовами."""

    def __init__(self, path: Path, lock_timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS) -> None:
        self.path = path
        self.lock_path = path.with_name(path.name + ".lock")
        self.lock_timeout = lock_timeout

    # --- чтение -------------------------------------------------------------

    def snapshot(self) -> Snapshot:
        """Читает файл под блокировкой, чтобы не застать его в момент замены."""
        with self._locked():
            return self._read_unlocked()

    def _locked(self) -> AbstractContextManager[None]:
        if not self.path.parent.is_dir():
            raise LeadError(
                ErrorCode.STORAGE_NOT_FOUND,
                f"directory of the leads file does not exist: {self.path.parent}",
                path=str(self.path),
            )
        return exclusive_lock(self.lock_path, self.lock_timeout)

    def list_leads(self, status: str | None = None) -> list[dict[str, Any]]:
        leads = self.snapshot().leads
        if status is not None:
            allowed = sorted({STATUS_NEW, STATUS_PROCESSED} | {lead["status"] for lead in leads})
            if status not in allowed:
                raise LeadError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"unknown status filter {status!r}; valid values: {allowed}",
                    valid=allowed,
                )
        return [
            {"id": lead["id"], "status": lead["status"]}
            for lead in leads
            if status is None or lead["status"] == status
        ]

    def get_lead(self, lead_id: LeadId) -> Lead:
        _require_valid_id(lead_id)
        return find_lead(self.snapshot().leads, lead_id)

    # --- запись -------------------------------------------------------------

    def update_lead(
        self,
        lead_id: LeadId,
        category: object,
        priority: object,
        status: object,
        draft_reply: object,
    ) -> UpdateResult:
        """Переводит заявку new -> processed. Повтор и конфликт файл не меняют."""
        _require_valid_id(lead_id)
        update = validate_update(category, priority, status, draft_reply)
        desired = update.as_fields()

        with self._locked():
            # Под блокировкой всегда берём актуальное содержимое, а не кэш.
            current = self._read_unlocked()
            lead = find_lead(current.leads, lead_id)
            lead_status = lead["status"]

            if lead_status == STATUS_PROCESSED:
                if all(key in lead and lead[key] == value for key, value in desired.items()):
                    return UpdateResult(lead_id, "unchanged")
                raise LeadError(
                    ErrorCode.CONFLICT,
                    f"lead {lead_id!r} is already processed with different values; "
                    "it was not overwritten",
                    id=lead_id,
                    current={
                        "status": lead_status,
                        "category": lead.get("category"),
                        "priority": lead.get("priority"),
                    },
                )
            if lead_status != STATUS_NEW:
                raise LeadError(
                    ErrorCode.CONFLICT,
                    f"lead {lead_id!r} has status {lead_status!r}; "
                    f"only {STATUS_NEW!r} leads can be processed",
                    id=lead_id,
                    current={"status": lead_status},
                )

            for key in EDITABLE_FIELDS:
                lead[key] = desired[key]
            self._write_unlocked(serialize_leads(current.leads, current.style))
            return UpdateResult(lead_id, "updated")

    def append_leads(self, new_leads: list[Lead]) -> list[LeadId]:
        """Добавляет новые заявки в конец файла (импорт из каналов). ID назначаются числами
        после максимального числового ID; существующие записи не меняются."""
        if not new_leads:
            return []
        with self._locked():
            current = self._read_unlocked()
            numeric = [lead["id"] for lead in current.leads if type(lead["id"]) is int]
            next_id = max(numeric, default=0) + 1
            assigned: list[LeadId] = []
            for lead in new_leads:
                record = {"id": next_id, **{k: v for k, v in lead.items() if k != "id"}}
                record["status"] = STATUS_NEW
                current.leads.append(record)
                assigned.append(next_id)
                next_id += 1
            self._write_unlocked(serialize_leads(current.leads, current.style))
            return assigned

    # --- внутреннее ---------------------------------------------------------

    def _read_unlocked(self) -> Snapshot:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError as exc:
            raise LeadError(
                ErrorCode.STORAGE_NOT_FOUND,
                f"leads file not found: {self.path}",
                path=str(self.path),
            ) from exc
        except OSError as exc:
            raise LeadError(
                ErrorCode.STORAGE_IO, f"cannot read leads file {self.path}: {exc.strerror or exc}"
            ) from exc
        leads = parse_leads(raw)
        return Snapshot(leads=leads, sha256=sha256_hex(raw), style=detect_style(raw, leads))

    def _write_unlocked(self, data: bytes) -> None:
        directory = self.path.parent
        self._remove_stale_temp_files()
        replaced = False
        tmp_name: str | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                dir=directory, prefix=f".{self.path.name}.", suffix=".tmp"
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            _copy_permissions(self.path, Path(tmp_name))
            _replace(tmp_name, self.path)
            replaced = True
            _fsync_directory(directory)
        except OSError as exc:
            if tmp_name is not None and not replaced:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_name)
            if replaced:
                raise LeadError(
                    ErrorCode.STORAGE_IO,
                    "the file was replaced but the directory sync failed; "
                    "the outcome is uncertain, check the lead state before retrying: "
                    f"{exc.strerror or exc}",
                    outcome="uncertain",
                ) from exc
            raise LeadError(
                ErrorCode.STORAGE_IO,
                f"write failed before the atomic replace, the file is unchanged: "
                f"{exc.strerror or exc}",
                outcome="not_written",
            ) from exc
        except BaseException:
            if tmp_name is not None and not replaced:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_name)
            raise

    def _remove_stale_temp_files(self) -> None:
        """Удаляет временные файлы, оставшиеся от аварийно завершённых писателей.

        Вызывается под блокировкой, поэтому любой такой файл гарантированно ничей.
        """
        for stale in self.path.parent.glob(f".{self.path.name}.*.tmp"):
            with contextlib.suppress(OSError):
                stale.unlink()


def _require_valid_id(lead_id: object) -> None:
    if not is_valid_lead_id(lead_id):
        raise LeadError(
            ErrorCode.INVALID_ARGUMENT,
            f"id must be an integer or a non-empty string, got {lead_id!r}",
        )


def _copy_permissions(source: Path, target: Path) -> None:
    """Сохраняет права и владельца исходного файла (mkstemp создаёт файл с 0600)."""
    with contextlib.suppress(OSError):
        info = source.stat()
        os.chmod(target, stat.S_IMODE(info.st_mode))
        if sys.platform != "win32":
            # Группу удаётся сохранить, если пользователь в неё входит; иначе оставляем как есть.
            with contextlib.suppress(OSError):
                os.chown(target, info.st_uid, info.st_gid)


def _replace(source: str, target: Path) -> None:
    if sys.platform != "win32":
        os.replace(source, target)
        return
    # В Windows замена кратковременно блокируется антивирусом или индексатором.
    for attempt in range(10):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.05)


def _fsync_directory(directory: Path) -> None:
    """Фиксирует запись каталога, чтобы переименование пережило отказ питания."""
    if sys.platform == "win32":
        return  # Windows не позволяет открыть каталог для fsync.
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
