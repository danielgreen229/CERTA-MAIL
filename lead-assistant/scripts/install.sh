#!/usr/bin/env bash
# Установка в каталог проекта: окружение Python, зависимости, сервер llama.cpp и модель.
# Запускается обычным пользователем из любого каталога; пути с пробелами поддерживаются.
#
#   scripts/install.sh                               # спросит модель и сборку (в терминале)
#   scripts/install.sh --model qwen3-14b --build cpu # без вопросов
#   scripts/install.sh --dev                         # плюс ruff, mypy, pytest
#   scripts/install.sh --no-llm                      # без загрузки модели (свой API: --llm-url)
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ "$(id -u)" -eq 0 ] && [ "${ALLOW_ROOT:-0}" != "1" ]; then
  echo "Не запускайте установку от root: проект рассчитан на обычного пользователя." >&2
  echo "Если это осознанно, повторите с ALLOW_ROOT=1." >&2
  exit 1
fi

LOCK="requirements.lock"
MODEL="${LEADS_LLM_MODEL:-}"
BUILD="${LEADS_LLM_BUILD:-}"
WITH_LLM=1
while [ $# -gt 0 ]; do
  case "$1" in
    --dev) LOCK="requirements-dev.lock" ;;
    --no-llm) WITH_LLM=0 ;;
    --model) MODEL="$2"; shift ;;
    --build) BUILD="$2"; shift ;;
    *) echo "Неизвестный параметр: $1" >&2; exit 2 ;;
  esac
  shift
done

PYTHON_BIN="${PYTHON:-python3.12}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Не найден $PYTHON_BIN. Установите Python 3.12: sudo apt install python3.12 python3.12-venv" >&2
  exit 1
fi
"$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' || {
  echo "Нужен Python 3.12 или новее, найден: $("$PYTHON_BIN" --version)" >&2
  exit 1
}
"$PYTHON_BIN" -c 'import ensurepip, venv' 2>/dev/null || {
  echo "В $PYTHON_BIN нет модуля venv. Установите: sudo apt install python3.12-venv" >&2
  exit 1
}

"$PYTHON_BIN" -m venv .venv
. scripts/_env.sh
"$PY" -m pip install --disable-pip-version-check --require-hashes -r "$LOCK"
"$PY" -m pip install --disable-pip-version-check --no-deps --no-build-isolation -e .

if [ ! -f data/leads.json ]; then
  cp data/leads.original.json data/leads.json
  echo "Создана рабочая копия data/leads.json (оригинал: data/leads.original.json)."
fi

if [ "$WITH_LLM" -eq 1 ]; then
  echo
  if [ -z "$MODEL" ] && [ -z "$BUILD" ] && [ -t 0 ]; then
    # Интерактивный запуск: модель и сборку выбирает пользователь.
    "$PY" -m lead_assistant.llm install --choose
  else
    # Без --model установщик берёт рекомендацию для этой машины (по памяти и сборке).
    "$PY" -m lead_assistant.llm install ${MODEL:+--model "$MODEL"} --build "${BUILD:-cpu}"
  fi
fi

echo
"$PY" -m lead_assistant.doctor || {
  echo
  echo "Установка завершена, но проверка нашла замечания (см. выше)." >&2
}
