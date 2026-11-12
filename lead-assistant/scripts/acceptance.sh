#!/usr/bin/env bash
# Приёмочный прогон на чистой копии исходника с локальной моделью.
# Пишет журнал в evidence/acceptance-<дата>.log и не трогает data/leads.json.
#
#   scripts/acceptance.sh                          # полный сценарий, включая набор для оценки
#   scripts/acceptance.sh --no-evals               # без синтетического набора
#   scripts/acceptance.sh --build vulkan           # остальные параметры уходят в process-leads
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
. scripts/_env.sh

WITH_EVALS=1
if [ "${1:-}" = "--no-evals" ]; then WITH_EVALS=0; shift; fi
MODEL_ARGS=("$@")

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="acceptance/$STAMP"
LOG="evidence/acceptance-$STAMP.log"
mkdir -p "$WORK" evidence
FAILED=0

step() {
  local title="$1"; shift
  echo
  echo "=== $title"
  echo "\$ $*"
  if "$@"; then echo "--- PASS: $title"; else echo "--- FAIL: $title (код $?)"; FAILED=$((FAILED + 1)); fi
}

checksum() { "$PY" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"; }

{
  echo "Приёмочный прогон $STAMP"
  uname -a
  "$PY" --version

  step "проверка установки" "$PY" -m lead_assistant.doctor --leads-file data/leads.original.json "${MODEL_ARGS[@]}"
  if [ "$FAILED" -ne 0 ]; then
    echo "Остановлено: исправьте замечания проверки и повторите."
    exit 1
  fi

  cp data/leads.original.json "$WORK/leads.json"
  echo "чистая копия: $WORK/leads.json sha256=$(checksum "$WORK/leads.json")"

  step "штатный прогон" "$PY" -m lead_assistant.cli --leads-file "$WORK/leads.json" --runs-dir "$WORK/runs" --save-dialog "${MODEL_ARGS[@]}"
  FIRST_RUN="$(ls -d "$WORK"/runs/2* | sort | tail -1)"
  SHA_AFTER_FIRST="$(checksum "$WORK/leads.json")"
  echo "sha256 после первого прогона: $SHA_AFTER_FIRST"

  step "сверка с оригиналом" "$PY" -m lead_assistant.verify data/leads.original.json "$WORK/leads.json" --expect-all-processed
  step "сверка реальных заявок по ID" "$PY" -m lead_assistant.evals real --processed "$WORK/leads.json" --run "$FIRST_RUN/run.json" --output "$WORK/real_eval.json"
  step "разбор первого прогона по трейсу" "$PY" -m lead_assistant.diagnose "$FIRST_RUN"

  step "повторный прогон на той же копии" "$PY" -m lead_assistant.cli --leads-file "$WORK/leads.json" --runs-dir "$WORK/runs" "${MODEL_ARGS[@]}"
  SHA_AFTER_SECOND="$(checksum "$WORK/leads.json")"
  echo "sha256 после повторного прогона: $SHA_AFTER_SECOND"
  step "контрольная сумма не изменилась" test "$SHA_AFTER_FIRST" = "$SHA_AFTER_SECOND"

  if [ "$WITH_EVALS" -eq 1 ]; then
    step "набор для оценки" "$PY" -m lead_assistant.evals synthetic --runs-dir "$WORK/eval-runs" "${MODEL_ARGS[@]}"
  fi

  echo
  echo "ИТОГ: не пройдено шагов: $FAILED. Материалы: $WORK, журнал: $LOG"
  exit "$FAILED"
} 2>&1 | tee "$LOG"
exit "${PIPESTATUS[0]}"
