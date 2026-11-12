@echo off
chcp 65001 >nul
echo ПРЕДВАРИТЕЛЬНАЯ ПРОВЕРКА, не приёмочный прогон: сводка, посчитанная по файлу
.venv\Scripts\python.exe scripts\show_head.py evidence\prelim\rules-1.1.0-real\runs\20261111T220601Z-a0b7a6\summary.md 26
echo $ python -m lead_assistant.verify data\leads.original.json ...\leads.json --expect-all-processed
.venv\Scripts\python.exe -m lead_assistant.verify data\leads.original.json evidence\prelim\rules-1.1.0-real\leads.json --expect-all-processed | findstr /c:"sha256" /c:"new:" /c:"без изменений" /c:"сверка"
