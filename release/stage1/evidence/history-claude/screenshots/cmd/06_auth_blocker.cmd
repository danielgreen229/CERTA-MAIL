@echo off
chcp 65001 >nul
copy /y data\leads.original.json %TEMP%\shot_leads.json >nul
echo $ process-leads   [рабочий путь: Claude Agent SDK, без авторизации Claude]
.venv\Scripts\process-leads.exe --leads-file %TEMP%\shot_leads.json --runs-dir %TEMP%\shot_runs 2>&1 | findstr /b /c:"[" /c:"Статус" /c:"- Найдено" /c:"- Записано" /c:"- AUTH"
echo.
echo $ leads-doctor
.venv\Scripts\leads-doctor.exe --leads-file data\leads.original.json | findstr /c:"авторизация" /c:"CLI" /c:"MCP"
