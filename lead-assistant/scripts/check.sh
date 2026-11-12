#!/usr/bin/env bash
# Проверки качества кода. Требуется установка с --dev.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
. scripts/_env.sh

echo "== ruff check"
"$PY" -m ruff check .
echo "== ruff format --check"
"$PY" -m ruff format --check .
echo "== mypy"
"$PY" -m mypy
echo "== pytest"
"$PY" -m pytest
