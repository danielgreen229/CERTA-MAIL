from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lead_assistant.storage import LeadStore
from tests.helpers import ORIGINAL


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def leads_file(tmp_path: Path) -> Path:
    """Рабочая копия реального файла в каталоге с пробелами и кириллицей."""
    directory = tmp_path / "каталог с пробелами"
    directory.mkdir()
    target = directory / "leads.json"
    shutil.copyfile(ORIGINAL, target)
    return target


@pytest.fixture
def store(leads_file: Path) -> LeadStore:
    return LeadStore(leads_file, lock_timeout=5.0)
