@echo off
chcp 65001 >nul
copy /y data\leads.original.json %TEMP%\shot_leads.json >nul
echo $ list_leads status=processed
.venv\Scripts\python.exe -m lead_assistant.mcp_call --leads-file %TEMP%\shot_leads.json list_leads --args-file evidence\screenshots\args\list.json
echo $ get_lead id="3"   [тип ID сохраняется: строка "3" - это не число 3]
.venv\Scripts\python.exe -m lead_assistant.mcp_call --leads-file %TEMP%\shot_leads.json get_lead --args-file evidence\screenshots\args\wrong_type.json
echo.
echo $ update_lead: значения, которых требует текст заявки 6 [high, VIP, скидка 90%%]
.venv\Scripts\python.exe -m lead_assistant.mcp_call --leads-file %TEMP%\shot_leads.json update_lead --args-file evidence\screenshots\args\injection.json
echo.
echo $ update_lead: спам, первая запись
.venv\Scripts\python.exe -m lead_assistant.mcp_call --leads-file %TEMP%\shot_leads.json update_lead --args-file evidence\screenshots\args\spam.json
echo $ update_lead: повтор с теми же значениями
.venv\Scripts\python.exe -m lead_assistant.mcp_call --leads-file %TEMP%\shot_leads.json update_lead --args-file evidence\screenshots\args\spam.json
echo $ update_lead: другие значения для уже обработанной заявки
.venv\Scripts\python.exe -m lead_assistant.mcp_call --leads-file %TEMP%\shot_leads.json update_lead --args-file evidence\screenshots\args\conflict.json
