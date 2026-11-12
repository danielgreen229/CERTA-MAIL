from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from lead_assistant import storage
from lead_assistant.models import MAX_DRAFT_CHARS, ErrorCode, LeadError
from lead_assistant.storage import (
    LeadStore,
    detect_style,
    parse_leads,
    serialize_leads,
    sha256_hex,
)
from tests.helpers import ORIGINAL, finish_worker, start_worker

VALID = ("question", "medium", "processed", "Здравствуйте! Уточните, пожалуйста, маршрут.")


def sha(path: Path) -> str:
    return sha256_hex(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def error_code(call: Any) -> ErrorCode:
    with pytest.raises(LeadError) as caught:
        call()
    return caught.value.code


# --- чтение и оформление ---------------------------------------------------------


def test_original_roundtrip_is_byte_identical() -> None:
    raw = ORIGINAL.read_bytes()
    leads = parse_leads(raw)
    style = detect_style(raw, leads)
    assert len(leads) == 15
    assert style.layout == "lines"
    assert serialize_leads(leads, style) == raw


def test_list_leads_filter(store: LeadStore) -> None:
    assert len(store.list_leads()) == 15
    new = store.list_leads("new")
    assert [item["id"] for item in new] == list(range(1, 15))
    assert all(set(item) == {"id", "status"} for item in new)
    assert store.list_leads("processed") == [{"id": 15, "status": "processed"}]


def test_list_leads_rejects_unknown_status(store: LeadStore) -> None:
    # Опечатка в фильтре не должна молча вернуть пустой список: это пропуск заявок.
    assert error_code(lambda: store.list_leads("New")) is ErrorCode.INVALID_ARGUMENT


def test_get_lead_preserves_id_type_and_reports_missing(store: LeadStore) -> None:
    lead = store.get_lead(15)
    assert lead["id"] == 15 and type(lead["id"]) is int
    assert lead["draft_reply"] == "Да, перенесли встречу на четверг."

    with pytest.raises(LeadError) as wrong_type:
        store.get_lead("15")
    assert wrong_type.value.code is ErrorCode.NOT_FOUND
    assert "exists" in wrong_type.value.message  # подсказка о типе ID

    assert error_code(lambda: store.get_lead(999)) is ErrorCode.NOT_FOUND
    assert error_code(lambda: store.get_lead(True)) is ErrorCode.INVALID_ARGUMENT
    assert error_code(lambda: store.get_lead("")) is ErrorCode.INVALID_ARGUMENT


def test_string_ids_are_supported(tmp_path: Path) -> None:
    path = tmp_path / "leads.json"
    write_json(path, [{"id": "A-17", "text": "t", "status": "new"}, {"id": 2, "status": "new"}])
    store = LeadStore(path)
    assert store.get_lead("A-17")["id"] == "A-17"
    assert store.update_lead("A-17", *VALID).result == "updated"
    assert store.get_lead("A-17")["status"] == "processed"
    assert store.list_leads("new") == [{"id": 2, "status": "new"}]


# --- запись ------------------------------------------------------------------------


def test_update_changes_only_target_line_and_allowed_fields(
    store: LeadStore, leads_file: Path
) -> None:
    before_lines = leads_file.read_bytes().split(b"\n")
    assert store.update_lead(4, *VALID).result == "updated"
    after_lines = leads_file.read_bytes().split(b"\n")

    changed = [i for i, (a, b) in enumerate(zip(before_lines, after_lines, strict=True)) if a != b]
    assert changed == [4]  # строка заявки 4; остальные байты прежние

    lead = store.get_lead(4)
    assert list(lead) == [
        "id", "date", "channel", "name", "contact", "text",
        "status", "category", "priority", "draft_reply",
    ]  # fmt: skip
    assert (lead["status"], lead["category"], lead["priority"]) == (
        "processed",
        "question",
        "medium",
    )
    original = parse_leads(ORIGINAL.read_bytes())[3]
    assert {k: lead[k] for k in original if k != "status"} == {
        k: v for k, v in original.items() if k != "status"
    }


def test_spam_is_stored_with_null_draft(store: LeadStore, leads_file: Path) -> None:
    store.update_lead(3, "spam", "low", "processed", None)
    assert '"priority": "low", "draft_reply": null}' in leads_file.read_text(encoding="utf-8")


def test_repeat_with_same_values_is_noop(store: LeadStore, leads_file: Path) -> None:
    store.update_lead(4, *VALID)
    checksum, mtime = sha(leads_file), leads_file.stat().st_mtime_ns
    assert store.update_lead(4, *VALID).result == "unchanged"
    # Пробелы по краям черновика не делают значение «другим».
    assert store.update_lead(4, "question", "medium", "processed", f"  {VALID[3]}\n").result == (
        "unchanged"
    )
    assert sha(leads_file) == checksum
    assert leads_file.stat().st_mtime_ns == mtime  # файл не переписывался


def test_conflict_keeps_file_unchanged(store: LeadStore, leads_file: Path) -> None:
    store.update_lead(4, *VALID)
    checksum = sha(leads_file)
    with pytest.raises(LeadError) as conflict:
        store.update_lead(4, "sale", "high", "processed", "Другой ответ")
    assert conflict.value.code is ErrorCode.CONFLICT
    assert conflict.value.details["current"]["category"] == "question"
    # Заявка, обработанная до нас (ID 15), тоже не перезаписывается.
    assert error_code(lambda: store.update_lead(15, *VALID)) is ErrorCode.CONFLICT
    assert sha(leads_file) == checksum


def test_non_new_status_cannot_be_processed(tmp_path: Path) -> None:
    path = tmp_path / "leads.json"
    write_json(path, [{"id": 1, "status": "archived"}])
    assert error_code(lambda: LeadStore(path).update_lead(1, *VALID)) is ErrorCode.CONFLICT


@pytest.mark.parametrize(
    ("args", "fragment"),
    [
        (("unknown", "medium", "processed", "x"), "category"),
        (("sale", "urgent", "processed", "x"), "priority"),
        (("sale", "medium", "new", "x"), "status"),
        (("sale", "medium", "VIP", "x"), "status"),
        (("sale", "medium", "processed", None), "draft_reply"),
        (("sale", "medium", "processed", "   "), "draft_reply"),
        (("sale", "medium", "processed", 42), "draft_reply"),
        (("sale", "medium", "processed", "x" * (MAX_DRAFT_CHARS + 1)), "too long"),
        (("spam", "low", "processed", "Ответ спамеру"), "null"),
        (("spam", "high", "processed", None), "low"),
    ],
)
def test_invalid_update_is_rejected_without_writing(
    store: LeadStore, leads_file: Path, args: tuple[Any, ...], fragment: str
) -> None:
    checksum = sha(leads_file)
    with pytest.raises(LeadError) as invalid:
        store.update_lead(1, *args)
    assert invalid.value.code is ErrorCode.INVALID_ARGUMENT
    assert fragment in invalid.value.message
    assert sha(leads_file) == checksum


def test_validation_reports_all_problems_at_once(store: LeadStore) -> None:
    with pytest.raises(LeadError) as invalid:
        store.update_lead(1, "x", "y", "z", "")
    assert len(invalid.value.details["problems"]) == 4


def test_update_missing_lead(store: LeadStore, leads_file: Path) -> None:
    checksum = sha(leads_file)
    assert error_code(lambda: store.update_lead(404, *VALID)) is ErrorCode.NOT_FOUND
    assert sha(leads_file) == checksum


# --- повреждённые данные -----------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b'[{"id": 1, "status": "new"}', ErrorCode.STORAGE_CORRUPT),
        (b"\xff\xfe not utf-8", ErrorCode.STORAGE_CORRUPT),
        (b'[{"id": 1, "status": "new", "x": NaN}]', ErrorCode.STORAGE_CORRUPT),
        (b'{"leads": []}', ErrorCode.STORAGE_INVALID),
        (b'[{"status": "new"}]', ErrorCode.STORAGE_INVALID),
        (b'[{"id": 1}]', ErrorCode.STORAGE_INVALID),
        (b'[{"id": 1.5, "status": "new"}]', ErrorCode.STORAGE_INVALID),
        (b'["not an object"]', ErrorCode.STORAGE_INVALID),
        (b'[{"id": 1, "status": "new", "status": "processed"}]', ErrorCode.STORAGE_INVALID),
        (b'[{"id": 1, "status": "new"}, {"id": 1, "status": "new"}]', ErrorCode.DUPLICATE_ID),
        (b'[{"id": 1, "status": "new"}, {"id": "1", "status": "new"}]', ErrorCode.DUPLICATE_ID),
    ],
)
def test_bad_files_give_clear_errors(tmp_path: Path, content: bytes, code: ErrorCode) -> None:
    path = tmp_path / "leads.json"
    path.write_bytes(content)
    store = LeadStore(path)
    assert error_code(store.list_leads) is code
    assert error_code(lambda: store.get_lead(1)) is code
    assert error_code(lambda: store.update_lead(1, *VALID)) is code
    assert path.read_bytes() == content  # повреждённый файл не трогаем


def test_missing_file(tmp_path: Path) -> None:
    store = LeadStore(tmp_path / "absent.json")
    assert error_code(store.list_leads) is ErrorCode.STORAGE_NOT_FOUND


def test_corrupt_error_points_to_position(tmp_path: Path) -> None:
    path = tmp_path / "leads.json"
    path.write_text('[\n  {"id": 1, "status": "new"},\n  {"id": 2 "status": "new"}\n]', "utf-8")
    with pytest.raises(LeadError) as corrupt:
        LeadStore(path).list_leads()
    assert corrupt.value.details["line"] == 3


# --- отказоустойчивость записи -----------------------------------------------------


def temp_files(leads_file: Path) -> list[Path]:
    return list(leads_file.parent.glob(f".{leads_file.name}.*.tmp"))


def test_failure_before_atomic_replace_leaves_file_intact(
    store: LeadStore, leads_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_source: str, _target: Path) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(storage, "_replace", fail)
    checksum = sha(leads_file)
    with pytest.raises(LeadError) as failed:
        store.update_lead(1, *VALID)
    assert failed.value.code is ErrorCode.STORAGE_IO
    assert failed.value.details["outcome"] == "not_written"
    assert sha(leads_file) == checksum
    assert temp_files(leads_file) == []  # временный файл убран

    monkeypatch.undo()
    assert store.update_lead(1, *VALID).result == "updated"  # блокировка освобождена


def test_uncertain_outcome_is_resolved_by_checking_state(
    store: LeadStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_directory: Path) -> None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(storage, "_fsync_directory", fail)
    with pytest.raises(LeadError) as uncertain:
        store.update_lead(1, *VALID)
    assert uncertain.value.code is ErrorCode.STORAGE_IO
    assert uncertain.value.details["outcome"] == "uncertain"

    monkeypatch.undo()
    # Правило при неясном исходе: сначала проверить состояние, потом решать о повторе.
    assert store.get_lead(1)["status"] == "processed"
    assert store.update_lead(1, *VALID).result == "unchanged"


def test_crash_before_replace_in_another_process(store: LeadStore, leads_file: Path) -> None:
    checksum = sha(leads_file)
    code, _ = finish_worker(
        start_worker(leads_file, "update", "1", "question", "medium", "x", "--crash-before-replace")
    )
    assert code == 17  # процесс погиб до os.replace
    assert sha(leads_file) == checksum
    assert len(parse_leads(leads_file.read_bytes())) == 15
    assert len(temp_files(leads_file)) == 1  # остался временный файл погибшего писателя

    # Блокировку снимает ОС; следующая запись проходит и убирает чужой временный файл.
    assert store.update_lead(1, *VALID).result == "updated"
    assert temp_files(leads_file) == []


def test_lock_timeout_when_another_process_holds_the_lock(leads_file: Path, tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    holder = start_worker(leads_file, "hold-lock", "3", str(ready))
    try:
        while not ready.exists():
            assert holder.poll() is None, holder.communicate()
        checksum = sha(leads_file)
        impatient = LeadStore(leads_file, lock_timeout=0.3)
        assert error_code(lambda: impatient.update_lead(1, *VALID)) is ErrorCode.LOCK_TIMEOUT
        assert sha(leads_file) == checksum
    finally:
        finish_worker(holder)
    assert LeadStore(leads_file).update_lead(1, *VALID).result == "updated"


def test_lock_file_is_stable_and_separate(store: LeadStore, leads_file: Path) -> None:
    store.update_lead(1, *VALID)
    lock = leads_file.with_name("leads.json.lock")
    assert lock.exists() and lock != leads_file
    first = lock.stat().st_ino if sys.platform != "win32" else None
    store.update_lead(2, *VALID)
    if first is not None:
        assert lock.stat().st_ino == first  # lock-файл не заменяется при записи данных


# --- оформление файла --------------------------------------------------------------


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("indent", [2, 4, None])
def test_formatting_styles_are_preserved(tmp_path: Path, newline: str, indent: int | None) -> None:
    leads = [{"id": 1, "text": "Привет", "status": "new"}, {"id": 2, "text": "б", "status": "new"}]
    text = json.dumps(leads, ensure_ascii=False, indent=indent) + "\n"
    path = tmp_path / "leads.json"
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    LeadStore(path).update_lead(1, *VALID)

    updated = {
        "id": 1, "text": "Привет", "status": "processed",
        "category": "question", "priority": "medium", "draft_reply": VALID[3],
    }  # fmt: skip
    wanted = json.dumps([updated, leads[1]], ensure_ascii=False, indent=indent) + "\n"
    assert path.read_bytes() == wanted.replace("\n", newline).encode("utf-8")


def test_bom_and_ascii_escapes_are_preserved(tmp_path: Path) -> None:
    leads = [{"id": 1, "text": "Привет", "status": "new"}]
    path = tmp_path / "leads.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(leads, indent=2).encode("ascii") + b"\n")
    LeadStore(path).update_lead(1, "spam", "low", "processed", None)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\\u041f" in raw and "Привет".encode() not in raw


@pytest.mark.posix
@pytest.mark.skipif(sys.platform == "win32", reason="права доступа POSIX")
def test_file_permissions_are_preserved(store: LeadStore, leads_file: Path) -> None:
    leads_file.chmod(0o640)
    store.update_lead(1, *VALID)
    assert stat.S_IMODE(leads_file.stat().st_mode) == 0o640


def test_missing_directory_is_reported_as_not_found(tmp_path: Path) -> None:
    store = LeadStore(tmp_path / "no such dir" / "leads.json")
    assert error_code(store.list_leads) is ErrorCode.STORAGE_NOT_FOUND
    assert error_code(lambda: store.update_lead(1, *VALID)) is ErrorCode.STORAGE_NOT_FOUND
    assert not (tmp_path / "no such dir").exists()  # каталог не создаётся молча
