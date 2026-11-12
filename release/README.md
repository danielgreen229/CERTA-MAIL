# Комплект сдачи — AI-помощник менеджера по заявкам, версия 2.0.0

| Что | Где |
|---|---|
| Архив исходников с готовой сборкой интерфейса | `lead-assistant-2.0.0.tar.gz` (+ `.sha256`) |
| Обработанный `leads.json` (реальный прогон модели, сверен по ID) | `leads.processed.json` |
| Отчёт проверки по критериям с доказательствами | `REVIEW.md` |
| Скриншоты работающей сборки (Playwright, 1440×900 и 390×844) | `screenshots/` |
| Журналы приёмки, проверок качества, прогоны модели | `evidence/` |
| Диалоги: разработка, демонстрация в Claude Code | `dialogs/` |
| Этап 1 (MCP + агент, отчёт 9/10) | `stage1/` |

Запуск: `docker compose up -d` (CPU) или
`docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d` (NVIDIA); без Docker —
`bash start.sh`. Адрес — `http://127.0.0.1:8000`, начальный пароль администратора — в
`data/initial-admin.txt` (в Docker: `docker compose exec web cat /data/initial-admin.txt`).
Подробности — `docs/OPERATIONS.md` и `docs/ARCHITECTURE.md` в архиве.
