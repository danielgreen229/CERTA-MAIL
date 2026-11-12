@echo off
chcp 65001 >nul
echo ПРЕДВАРИТЕЛЬНАЯ ПРОВЕРКА, не приёмочный прогон: сессия субагента, правила 1.1.0, копия реальных заявок
echo $ python scripts\show_trace.py ...\mcp_trace.jsonl
.venv\Scripts\python.exe scripts\show_trace.py evidence\prelim\rules-1.1.0-real\runs\20261111T220601Z-a0b7a6\mcp_trace.jsonl
