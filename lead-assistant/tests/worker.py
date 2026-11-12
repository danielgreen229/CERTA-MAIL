"""Независимый процесс-писатель для тестов параллельности и аварий.

    python worker.py LEADS_FILE update ID CATEGORY PRIORITY DRAFT [--go FILE]
        [--crash-before-replace]
    python worker.py LEADS_FILE hold-lock SECONDS READY_FILE

Печатает одну строку JSON с исходом.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from lead_assistant import storage
from lead_assistant.locking import exclusive_lock
from lead_assistant.models import LeadError
from lead_assistant.storage import LeadStore


def _wait_for(path: Path, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > deadline:
            raise TimeoutError(f"start signal {path} did not appear")
        time.sleep(0.005)


def main() -> int:
    leads_file = Path(sys.argv[1])
    command = sys.argv[2]
    store = LeadStore(leads_file, lock_timeout=30.0)

    if command == "hold-lock":
        seconds, ready = float(sys.argv[3]), Path(sys.argv[4])
        with exclusive_lock(store.lock_path, timeout=10.0):
            ready.write_text("locked", encoding="utf-8")
            time.sleep(seconds)
        print(json.dumps({"held": seconds}))
        return 0

    raw_id, category, priority, draft = sys.argv[3:7]
    lead_id: int | str = int(raw_id) if raw_id.lstrip("-").isdigit() else raw_id
    flags = sys.argv[7:]
    if "--crash-before-replace" in flags:
        # Имитация гибели процесса после записи временного файла, до атомарной замены.
        def crash(source: str, target: Path) -> None:
            os._exit(17)

        storage._replace = crash
    if "--go" in flags:
        _wait_for(Path(flags[flags.index("--go") + 1]))
    try:
        outcome = store.update_lead(
            lead_id, category, priority, "processed", None if draft == "null" else draft
        )
    except LeadError as error:
        print(json.dumps({"ok": False, "code": error.code.value, "pid": os.getpid()}))
        return 3
    print(json.dumps({"ok": True, "result": outcome.result, "pid": os.getpid()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
