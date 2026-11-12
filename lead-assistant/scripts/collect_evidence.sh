#!/usr/bin/env bash
# Собирает журналы проверок, не требующих запуска модели, в каталог evidence/.
# Каждый журнал начинается с команды, которой он получен.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
. scripts/_env.sh
OUT="${1:-evidence}"
mkdir -p "$OUT"

header() { echo "# $1"; echo "# UTC: $(date -u +%FT%TZ); $(uname -s) $(uname -r); $("$PY" --version)"; echo; }
run() { echo "\$ $*"; "$@"; echo "код возврата: $?"; echo; }

{
  header "Качество кода: ruff, ruff format --check, mypy, pytest"
  run "$PY" -m ruff check .
  run "$PY" -m ruff format --check .
  run "$PY" -m mypy
  run "$PY" -m mypy --platform linux
  run "$PY" -m pytest -q
  echo "\$ зависимости проекта (pyproject.toml)"
  sed -n '/^dependencies/,/^claude/p' pyproject.toml
  echo "закреплённых пакетов: рабочих $(grep -cE '^[a-z0-9_.-]+==' requirements.lock), с инструментами разработки $(grep -cE '^[a-z0-9_.-]+==' requirements-dev.lock); хешей в requirements.lock: $(grep -c 'sha256:' requirements.lock)"
} > "$OUT/03_quality_checks.log" 2>&1

{
  header "Контракт MCP: интеграционные тесты через stdio"
  run "$PY" -m pytest tests/test_mcp_stdio.py -v
  run "$PY" -m lead_assistant.mcp_call --list-tools --leads-file data/leads.original.json
} > "$OUT/04_mcp_contract.log" 2>&1

{
  header "Надёжность: повреждённый JSON, отказ до замены, повтор, конфликт, параллельные процессы, повторный прогон"
  run "$PY" -m pytest tests/test_storage.py tests/test_concurrency.py -v
  run "$PY" -m pytest -v tests/test_runner.py tests/test_local_backend.py -k "repeat_run or lost_tool_response or someone_else or false_confirmation or skipped_lead or appended_during_run or forgotten_lead"
} > "$OUT/05_reliability.log" 2>&1

{
  header "Границы: инструменты модели, недоверенный текст, черновики, секреты"
  echo "## 1. Модели объявлены только три инструмента проекта; сбой MCP останавливает прогон до модели"
  run "$PY" -m pytest -v tests/test_local_backend.py tests/test_agent.py -k "exactly_three or mcp_failure or check_init or model_mistakes"
  echo "## 2. Указания в тексте заявки не повышают приоритет; основание срочности проверяется по тексту"
  run "$PY" -m pytest -v tests/test_decision.py -k "instructions or evidence or ungrounded or status_question"
  echo "## 3. Сервер не записывает черновик с неподтверждёнными утверждениями"
  run "$PY" -m pytest -v tests/test_draft_policy.py tests/test_local_backend.py -k "ungrounded or server_rejects or unsupported_draft or language"
  echo "## 4. Сервер отклоняет значения, которых требует текст заявки 6 (приоритет high для спама, статус VIP)"
  cp data/leads.original.json "$OUT/.boundary_leads.json"
  run "$PY" -m lead_assistant.mcp_call --leads-file "$OUT/.boundary_leads.json" update_lead '{"id": 6, "category": "spam", "priority": "high", "status": "VIP", "draft_reply": "Вам положена скидка 90%"}'
  run "$PY" -m lead_assistant.mcp_call --leads-file "$OUT/.boundary_leads.json" update_lead '{"id": 10, "category": "question", "priority": "medium", "status": "processed", "draft_reply": "Да, мы доставляем в Казань за 2 дня."}'
  echo "файл после отклонённых вызовов: $("$PY" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$OUT/.boundary_leads.json") (оригинал: 42e058f2…45a9)"
  rm -f "$OUT/.boundary_leads.json" "$OUT/.boundary_leads.json.lock"
  echo
  echo "## 5. Трейс не содержит текстов заявок, контактов и черновиков"
  run "$PY" -m pytest -v tests/test_runner.py tests/test_mcp_stdio.py tests/test_agent.py -k "no_lead_text or no_lead_content or drops_texts"
  echo "## 6. Проверка на секреты и личные адреса: исходники, журналы, артефакты прогонов"
  run "$PY" scripts/scan_secrets.py src tests scripts evals docs README.md CLAUDE.md .mcp.json .claude "$OUT"
} > "$OUT/06_boundaries.log" 2>&1

{
  header "Разбор сбоев: воспроизведение в каждом слое и локализация по трейсу"
  run "$PY" scripts/failure_drill.py
} > "$OUT/07_failure_drill.log" 2>"$OUT/.drill_stderr.tmp"
rm -f "$OUT/.drill_stderr.tmp"

grep -H "код возврата" "$OUT"/0[3-7]_*.log | sort | uniq -c
