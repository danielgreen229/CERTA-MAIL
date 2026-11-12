@echo off
chcp 65001 >nul
.venv\Scripts\python.exe evidence\screenshots\cmd\noquickedit.py
echo $ ruff check .
.venv\Scripts\python.exe -m ruff check .
echo $ ruff format --check .
.venv\Scripts\python.exe -m ruff format --check .
echo $ mypy
.venv\Scripts\python.exe -m mypy
echo $ pytest -q
.venv\Scripts\python.exe -m pytest -q
