#!/usr/bin/env bash
# Запуск рабочего места одной командой (без Docker): bash start.sh
#
# Проверяет окружение, при первом запуске создаёт виртуальное окружение и ставит
# зафиксированные зависимости (scripts/install.sh), безопасно инициализирует данные
# (рабочая копия leads.json создаётся, только если её нет), запускает API и фоновый
# обработчик, проверяет доступность и печатает адрес. Повторный запуск сохраняет
# данные и настройки. Остановка: bash stop.sh
#
# Переменные: LEADS_PORT (8000), LEADS_HOST (127.0.0.1), LEADS_LLM_MODEL, LEADS_LLM_BUILD,
# LEADS_LLM_URL (внешний OpenAI-совместимый сервер вместо локальной модели).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PORT="${LEADS_PORT:-8000}"
HOST="${LEADS_HOST:-127.0.0.1}"
RUN_DIR="data/.run"

say() { printf '%s\n' "$*"; }

# 1. Окружение
command -v curl >/dev/null 2>&1 || { say "Нужна утилита curl" >&2; exit 1; }
if [ ! -d .venv ]; then
  say "== Первый запуск: установка окружения и модели"
  args=()
  [ -n "${LEADS_LLM_URL:-}" ] && args+=(--no-llm)
  bash scripts/install.sh "${args[@]}"
fi
. scripts/_env.sh
if [ -x ".venv/bin/leads-web" ]; then BIN=".venv/bin"; else BIN=".venv/Scripts"; fi
if [ ! -f web/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    say "== Сборка интерфейса"
    (cd web && npm ci --no-audit --no-fund && npm run build)
  else
    say "Нет собранного интерфейса web/dist и нет npm для сборки" >&2
    exit 1
  fi
fi

# 2. Данные: только если их ещё нет
mkdir -p data runs "$RUN_DIR"
chmod 700 data "$RUN_DIR" 2>/dev/null || true
export LEADS_DATA_DIR="$PWD/data" LEADS_RUNS_DIR="$PWD/runs" LEADS_STATIC_DIR="$PWD/web/dist"
export LEADS_SEED_FILE="$PWD/data/leads.original.json" LEADS_HOST="$HOST" LEADS_PORT="$PORT"
export PYTHONIOENCODING=utf-8

# 3. Уже запущено?
if curl -fsS "http://$HOST:$PORT/api/health" >/dev/null 2>&1; then
  say "Приложение уже работает: http://$HOST:$PORT"
  exit 0
fi

# 4. Запуск API и обработчика в фоне
nohup "$BIN/leads-web" > "$RUN_DIR/web.log" 2>&1 &
echo $! > "$RUN_DIR/web.pid"
nohup "$BIN/leads-worker" > "$RUN_DIR/worker.log" 2>&1 &
echo $! > "$RUN_DIR/worker.pid"

# 5. Проверка доступности
for _ in $(seq 1 60); do
  if curl -fsS "http://$HOST:$PORT/api/health" >/dev/null 2>&1; then
    say ""
    say "Рабочее место запущено: http://$HOST:$PORT"
    if [ -f data/initial-admin.txt ]; then
      say "Первый вход: логин и начальный пароль — в файле data/initial-admin.txt"
      say "(доступен только владельцу; пароль нужно сменить при первом входе, файл удалится сам)."
    fi
    say "Журналы: $RUN_DIR/web.log, $RUN_DIR/worker.log · остановка: bash stop.sh"
    exit 0
  fi
  if ! kill -0 "$(cat "$RUN_DIR/web.pid")" 2>/dev/null; then
    say "API не запустился, см. $RUN_DIR/web.log:" >&2
    tail -20 "$RUN_DIR/web.log" >&2
    exit 1
  fi
  sleep 1
done
say "API не ответил за 60 с, см. $RUN_DIR/web.log" >&2
exit 1
