@echo off
chcp 65001 >nul
.venv\Scripts\python.exe evidence\screenshots\cmd\noquickedit.py
for /f "delims=" %%d in ('dir /b /ad /o-n %TEMP%\lead_demo\runs') do set RUN=%%d
echo $ python scripts\show_trace.py runs\%RUN%\mcp_trace.jsonl   [первый прогон: трейс MCP-сервера]
.venv\Scripts\python.exe scripts\show_trace.py %TEMP%\lead_demo\runs\%RUN%\mcp_trace.jsonl
