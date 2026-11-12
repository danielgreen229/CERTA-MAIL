"""Резервная копия и восстановление данных рабочего места.

Копия — архив tar.gz: ``leads.json`` (снят под той же блокировкой, что и запись),
согласованный снимок SQLite (штатный backup API, безопасен при работающем
приложении), загруженные документы и ``manifest.json`` с контрольными суммами.
Восстановление проверяет суммы и заменяет файлы атомарно; перед ним текущие данные
сохраняются в отдельную копию. Восстанавливать нужно при остановленных API и
обработчике.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from lead_assistant.locking import exclusive_lock
from lead_assistant.storage import LeadStore, parse_leads
from lead_assistant.web.config import AppPaths


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _add(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(datetime.now(UTC).timestamp())
    archive.addfile(info, io.BytesIO(data))


def create_backup(paths: AppPaths, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / f"leads-backup-{stamp}.tar.gz"
    store = LeadStore(paths.leads_file)
    with exclusive_lock(store.lock_path, store.lock_timeout):
        leads = paths.leads_file.read_bytes()
    parse_leads(leads)  # в копию не попадает повреждённый файл
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "app.db"
        source = sqlite3.connect(paths.db_file)
        dest = sqlite3.connect(snapshot)
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()
        database = snapshot.read_bytes()
    files = {"leads.json": leads, "app.db": database}
    if paths.uploads_dir.is_dir():
        for upload in sorted(paths.uploads_dir.iterdir()):
            if upload.is_file():
                files[f"uploads/{upload.name}"] = upload.read_bytes()
    manifest = {
        "created_at": stamp,
        "files": {name: {"sha256": _sha(data), "size": len(data)} for name, data in files.items()},
    }
    with tarfile.open(target, "w:gz") as archive:
        for name, data in files.items():
            _add(archive, name, data)
        _add(archive, "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
    target.chmod(0o600)
    return target


def restore_backup(paths: AppPaths, archive_path: Path) -> dict[str, object]:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = {m.name: m for m in archive.getmembers() if m.isfile()}
        manifest_member = members.get("manifest.json")
        if manifest_member is None:
            raise ValueError("в архиве нет manifest.json")
        manifest = json.loads(archive.extractfile(manifest_member).read())  # type: ignore[union-attr]
        files: dict[str, bytes] = {}
        for name, meta in manifest["files"].items():
            if name.startswith(("/", "..")) or ".." in Path(name).parts:
                raise ValueError(f"недопустимый путь в архиве: {name}")
            data = archive.extractfile(members[name]).read()  # type: ignore[union-attr]
            if _sha(data) != meta["sha256"]:
                raise ValueError(f"контрольная сумма не совпала: {name}")
            files[name] = data
    parse_leads(files["leads.json"])
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    safety = None
    if paths.leads_file.exists() and paths.db_file.exists():
        safety = create_backup(paths, paths.data_dir / "backups" / "before-restore")
    targets = {"leads.json": paths.leads_file, "app.db": paths.db_file}
    for name, data in files.items():
        target = targets.get(name) or paths.uploads_dir / Path(name).name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".restore")
        temporary.write_bytes(data)
        os.replace(temporary, target)
    for suffix in ("-wal", "-shm"):
        Path(str(paths.db_file) + suffix).unlink(missing_ok=True)
    return {"restored": sorted(files), "safety_copy": str(safety) if safety else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="leads-backup", description="Резервная копия данных")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="сделать копию")
    create.add_argument("--to", default=None, help="каталог (по умолчанию data/backups)")
    restore = commands.add_parser("restore", help="восстановить из копии (приложение остановлено)")
    restore.add_argument("archive")
    args = parser.parse_args(argv)
    paths = AppPaths.from_env()
    if args.command == "create":
        target = create_backup(paths, Path(args.to) if args.to else paths.data_dir / "backups")
        print(f"копия: {target}")
    else:
        print(json.dumps(restore_backup(paths, Path(args.archive)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
