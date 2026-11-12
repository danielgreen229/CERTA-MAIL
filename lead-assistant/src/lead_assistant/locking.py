"""Межпроцессная блокировка через отдельный стабильный lock-файл.

Lock-файл никогда не заменяется и не удаляется, поэтому блокировка не теряется при
атомарной замене файла данных. На POSIX используется flock, на Windows — msvcrt.locking.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from lead_assistant.models import ErrorCode, LeadError

_POLL_INTERVAL_SECONDS = 0.02

if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def exclusive_lock(lock_path: Path, timeout: float) -> Iterator[None]:
    """Удерживает исключительную блокировку lock-файла на время блока.

    Ядро снимает блокировку при завершении процесса, поэтому аварийно завершённый
    писатель не оставляет «вечной» блокировки.
    """
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as exc:
        raise LeadError(
            ErrorCode.STORAGE_IO, f"cannot open lock file {lock_path}: {exc.strerror or exc}"
        ) from exc
    try:
        deadline = time.monotonic() + timeout
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise LeadError(
                    ErrorCode.LOCK_TIMEOUT,
                    f"could not acquire the write lock within {timeout:.1f}s; "
                    "another process is holding it",
                    lock_file=str(lock_path),
                )
            time.sleep(_POLL_INTERVAL_SECONDS)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)
