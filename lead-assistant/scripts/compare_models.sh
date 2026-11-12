#!/usr/bin/env bash
# Сравнение моделей на наборе для оценки и на копии реальных заявок.
#
#   scripts/compare_models.sh ИМЯ МОДЕЛЬ СБОРКА [доп. параметры process-leads]
#   scripts/compare_models.sh 14b qwen3-14b vulkan
#   scripts/compare_models.sh 14b-think qwen3-14b vulkan --think
#
# Результаты: compare/ИМЯ/{synthetic,real}/…, итоговая строка в compare/ИМЯ/result.txt
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
. scripts/_env.sh

NAME="$1"; MODEL="$2"; BUILD="$3"; shift 3
OUT="compare/$NAME"
rm -rf "$OUT"
mkdir -p "$OUT/real"

run_seconds() { local start=$SECONDS; "$@"; echo $((SECONDS - start)) > "$OUT/.seconds"; }

echo "=== [$NAME] набор для оценки"
run_seconds "$PY" -m lead_assistant.evals synthetic --runs-dir "$OUT/synthetic" --model "$MODEL" --build "$BUILD" --save-dialog "$@" > "$OUT/synthetic.log" 2>&1
SYN_SECONDS=$(cat "$OUT/.seconds")
grep -E "FAIL|Итог" "$OUT/synthetic.log"

echo "=== [$NAME] реальные заявки"
cp data/leads.original.json "$OUT/real/leads.json"
run_seconds "$PY" -m lead_assistant.cli --leads-file "$OUT/real/leads.json" --runs-dir "$OUT/real/runs" --model "$MODEL" --build "$BUILD" --today 2026-11-12 --save-dialog "$@" > "$OUT/real.log" 2>&1
REAL_SECONDS=$(cat "$OUT/.seconds")
grep -E "Статус|метрики" "$OUT/real.log"
RUN="$(ls -d "$OUT"/real/runs/2* | tail -1)"
"$PY" -m lead_assistant.verify data/leads.original.json "$OUT/real/leads.json" --expect-all-processed > "$OUT/real_verify.log" 2>&1
echo "сверка с оригиналом: код $?"
"$PY" -m lead_assistant.evals real --processed "$OUT/real/leads.json" --run "$RUN/run.json" --output "$OUT/real_eval.json" > "$OUT/real_eval.log" 2>&1
grep -E "FAIL|Итог" "$OUT/real_eval.log"

{
  echo "$NAME: модель $MODEL, сборка $BUILD, параметры: ${*:-нет}"
  echo "  набор для оценки ($SYN_SECONDS с): $(grep -E '^Итог' "$OUT/synthetic.log")"
  echo "  реальные заявки ($REAL_SECONDS с): $(grep -E '^Итог' "$OUT/real_eval.log")"
} | tee "$OUT/result.txt"
rm -f "$OUT/.seconds"
