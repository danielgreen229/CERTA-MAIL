@echo off
chcp 65001 >nul
echo $ ruff check .
.venv\Scripts\python.exe -m ruff check .
echo $ ruff format --check .
.venv\Scripts\python.exe -m ruff format --check .
echo $ mypy
.venv\Scripts\python.exe -m mypy
echo $ pytest -q
.venv\Scripts\python.exe -m pytest -q
