@echo off
chcp 65001 >nul
.venv\Scripts\python.exe evidence\screenshots\cmd\noquickedit.py
for /f "delims=" %%d in ('dir /b /ad /o-n %TEMP%\lead_demo\runs') do if not defined RUN set RUN=%%d
echo $ type runs\%RUN%\summary.md  [первые 33 строки]
.venv\Scripts\python.exe scripts\show_head.py %TEMP%\lead_demo\runs\%RUN%\summary.md 33
echo $ python -m lead_assistant.verify data\leads.original.json leads.json --expect-all-processed
.venv\Scripts\python.exe -m lead_assistant.verify data\leads.original.json %TEMP%\lead_demo\leads.json --expect-all-processed | findstr /c:"sha256" /c:"new:" /c:"без изменений" /c:"сверка"
