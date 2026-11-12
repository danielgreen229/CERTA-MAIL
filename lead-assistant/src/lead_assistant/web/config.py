"""Настройки приложения: пути, часовой пояс, сроки реакции, назначение ответственных.

Значения по умолчанию — демонстрационные и помечены флагом ``demo``. Изменённые через
интерфейс настройки хранятся в SQLite и переживают перезапуск.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENV_DATA_DIR = "LEADS_DATA_DIR"
ENV_LEADS_FILE = "LEADS_FILE"
ENV_RUNS_DIR = "LEADS_RUNS_DIR"
ENV_HOST = "LEADS_HOST"
ENV_PORT = "LEADS_PORT"
ENV_STATIC_DIR = "LEADS_STATIC_DIR"
ENV_SEED_FILE = "LEADS_SEED_FILE"

# Демонстрационные настройки: сроки реакции по приоритету (рабочие часы), рабочий
# календарь и правила назначения. В интерфейсе видны с пометкой «демо».
DEFAULT_SETTINGS: dict[str, Any] = {
    "demo": True,
    "timezone": "Europe/Moscow",
    "work_hours": {"start": 9, "end": 18, "days": [0, 1, 2, 3, 4]},
    "sla_hours": {"high": 2, "medium": 8, "low": 24},
    "assignment": {
        "complaint": "Отдел претензий",
        "sale": "Отдел продаж",
        "question": "Дежурный менеджер",
        "spam": None,
    },
    "model": {"backend": "local", "model": "", "build": "", "llm_url": ""},
    "schedule": {"enabled": False, "interval_minutes": 60},
    # Фоновая проверка подключённых ящиков и Telegram; новые письма сразу разбирает агент.
    "mail_check": {"enabled": True, "interval_seconds": 60, "auto_process": True},
}


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path
    leads_file: Path
    runs_dir: Path
    db_file: Path
    uploads_dir: Path
    static_dir: Path

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> AppPaths:
        root = project_root or Path.cwd()
        data_dir = Path(os.environ.get(ENV_DATA_DIR) or root / "data").resolve()
        leads = Path(os.environ.get(ENV_LEADS_FILE) or data_dir / "leads.json").resolve()
        runs = Path(os.environ.get(ENV_RUNS_DIR) or root / "runs").resolve()
        static = Path(os.environ.get(ENV_STATIC_DIR) or root / "web" / "dist").resolve()
        return cls(
            data_dir=data_dir,
            leads_file=leads,
            runs_dir=runs,
            db_file=data_dir / "app.db",
            uploads_dir=data_dir / "uploads",
            static_dir=static,
        )

    def ensure(self) -> None:
        for directory in (self.data_dir, self.runs_dir, self.uploads_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.seed_leads()

    def seed_leads(self) -> bool:
        """Безопасная инициализация: копирует исходный JSON, только если рабочего файла нет.

        Повторный запуск ничего не перезаписывает: данные и настройки сохраняются.
        """
        seed = os.environ.get(ENV_SEED_FILE)
        if self.leads_file.exists() or not seed or not Path(seed).is_file():
            return False
        self.leads_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.leads_file.with_name(self.leads_file.name + ".seed")
        shutil.copyfile(seed, temporary)
        os.replace(temporary, self.leads_file)
        return True
