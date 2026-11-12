#!/usr/bin/env bash
# Останавливает API и фоновый обработчик, запущенные start.sh. Данные не трогает.
# Незавершённая задача обработки продолжится после следующего запуска.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
for name in worker web; do
  pid_file="data/.run/$name.pid"
  if [ -f "$pid_file" ]; then
    pid="$(cat "$pid_file")"
    kill "$pid" 2>/dev/null && echo "остановлен $name ($pid)"
    rm -f "$pid_file"
  fi
done
