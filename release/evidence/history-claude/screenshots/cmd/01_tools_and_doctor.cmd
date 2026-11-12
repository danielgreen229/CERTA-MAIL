@echo off
chcp 65001 >nul
echo $ python -m lead_assistant.mcp_call --list-tools
.venv\Scripts\python.exe -m lead_assistant.mcp_call --list-tools --leads-file data\leads.original.json
echo.
echo $ leads-doctor
.venv\Scripts\leads-doctor.exe --leads-file data\leads.original.json
