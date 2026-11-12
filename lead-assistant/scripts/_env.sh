# Общая часть скриптов: путь к интерпретатору локального окружения.
# В Linux это .venv/bin/python; ветка Scripts нужна только для проверки в Git Bash на Windows.
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
else
  echo "Локальное окружение не найдено. Сначала выполните scripts/install.sh" >&2
  exit 1
fi
