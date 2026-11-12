# lead-assistant · Certa

AI-помощник менеджера по заявкам: MCP-сервер над `leads.json`, агент на бесплатной локальной
модели и рабочее место «Почта Certa». Полное описание — модули и функции, запуск, диаграммы,
API, решения и ограничения — в [README репозитория](../README.md).

## Коротко

```bash
bash scripts/install.sh && .venv/bin/process-leads    # агент одной командой (Windows: .venv/Scripts/)
docker compose up -d                                  # рабочее место на http://127.0.0.1:8000
docker compose exec web cat /data/initial-admin.txt   # начальный пароль администратора
```

В Claude Code: откройте эту папку и введите `/process-leads` — проектный `.mcp.json` подключит
MCP-сервер `leads`, `CLAUDE.md` — правила агента.

```bash
bash scripts/check.sh          # ruff, mypy strict, pytest
cd web && npm run build        # vue-tsc и сборка интерфейса
```
