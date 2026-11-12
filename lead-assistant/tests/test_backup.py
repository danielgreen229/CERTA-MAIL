"""Резервная копия: снимок данных, проверка сумм, восстановление с копией «до»."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from lead_assistant.storage import LeadStore, sha256_hex
from lead_assistant.web.backup import create_backup, restore_backup
from lead_assistant.web.db import connect
from tests.web_helpers import PROCESSED, client_for, make_paths


def test_backup_and_restore_round_trip(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, PROCESSED)
    with client_for(paths) as client:
        client.post("/api/leads/2/decision", json={"action": "accept", "result_version": 1})
    original = sha256_hex(paths.leads_file.read_bytes())
    archive = create_backup(paths, tmp_path / "backups")

    # Порча данных после копии: файл заявок и решение менеджера пропали.
    paths.leads_file.write_text("[]", encoding="utf-8")
    conn = connect(paths.db_file)
    conn.execute("DELETE FROM decisions")
    conn.close()

    result = restore_backup(paths, archive)
    assert result["safety_copy"], "текущие данные сохраняются перед восстановлением"
    assert sha256_hex(paths.leads_file.read_bytes()) == original
    conn = connect(paths.db_file)
    assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 1
    conn.close()
    assert len(LeadStore(paths.leads_file).snapshot().leads) == 15


def test_damaged_backup_is_refused(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, PROCESSED)
    with client_for(paths):
        pass
    archive = create_backup(paths, tmp_path / "backups")
    broken = tmp_path / "broken.tar.gz"
    with tarfile.open(archive, "r:gz") as source, tarfile.open(broken, "w:gz") as target:
        for member in source.getmembers():
            data = source.extractfile(member)
            assert data is not None
            content = data.read()
            if member.name == "leads.json":
                content = content.replace(b"processed", b"PROCESSED", 1)
            member.size = len(content)
            import io

            target.addfile(member, io.BytesIO(content))
    before = sha256_hex(paths.leads_file.read_bytes())
    with pytest.raises(ValueError, match="контрольная сумма"):
        restore_backup(paths, broken)
    assert sha256_hex(paths.leads_file.read_bytes()) == before
