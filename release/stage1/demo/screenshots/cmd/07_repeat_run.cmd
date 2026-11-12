@echo off
chcp 65001 >nul
.venv\Scripts\python.exe evidence\screenshots\cmd\noquickedit.py
echo $ certutil -hashfile leads.json SHA256   [до повторного прогона]
certutil -hashfile %TEMP%\lead_demo\leads.json SHA256 | findstr /v /c:"CertUtil" /c:"SHA256"
echo $ process-leads   [повторный прогон на той же копии]
.venv\Scripts\process-leads.exe --leads-file %TEMP%\lead_demo\leads.json --runs-dir %TEMP%\lead_demo\runs --build vulkan --today 2026-11-12 | findstr /b /c:"[" /c:"  [" /c:"Статус" /c:"- Найдено" /c:"- Записано" /c:"- Осталось"
echo $ certutil -hashfile leads.json SHA256   [после]
certutil -hashfile %TEMP%\lead_demo\leads.json SHA256 | findstr /v /c:"CertUtil" /c:"SHA256"
