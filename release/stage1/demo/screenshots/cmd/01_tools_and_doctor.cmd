@echo off
chcp 65001 >nul
.venv\Scripts\python.exe evidence\screenshots\cmd\noquickedit.py
echo $ python -m lead_assistant.mcp_call --list-tools
.venv\Scripts\python.exe -m lead_assistant.mcp_call --list-tools --leads-file data\leads.original.json
echo.
echo $ leads-doctor --build vulkan
.venv\Scripts\leads-doctor.exe --leads-file data\leads.original.json --build vulkan
