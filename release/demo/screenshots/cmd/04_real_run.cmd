@echo off
chcp 65001 >nul
.venv\Scripts\python.exe evidence\screenshots\cmd\noquickedit.py
if exist %TEMP%\lead_demo rmdir /s /q %TEMP%\lead_demo
mkdir %TEMP%\lead_demo
copy /y data\leads.original.json %TEMP%\lead_demo\leads.json >nul
echo $ process-leads --leads-file %%TEMP%%\lead_demo\leads.json --build vulkan
.venv\Scripts\process-leads.exe --leads-file %TEMP%\lead_demo\leads.json --runs-dir %TEMP%\lead_demo\runs --build vulkan --today 2026-11-12
