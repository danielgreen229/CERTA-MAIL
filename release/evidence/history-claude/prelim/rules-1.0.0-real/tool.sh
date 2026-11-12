#!/usr/bin/env bash
# Обёртка трёх MCP-инструментов для предварительной проверки (вызов через stdio).
cd "C:/Users/Dozer/Desktop/work/CERTATZ/TZ/lead-assistant"
export LEADS_FILE="C:\Users\Dozer\Desktop\work\CERTATZ\TZ\lead-assistant\surrogate\real\leads.json"
export LEADS_TRACE_FILE="C:\Users\Dozer\Desktop\work\CERTATZ\TZ\lead-assistant\surrogate\real\runs\20261111T215958Z-7683ed\mcp_trace.jsonl"
export LEADS_RUN_ID="20261111T215958Z-7683ed"
if [ -f "$2" ]; then exec .venv/Scripts/python.exe -m lead_assistant.mcp_call "$1" --args-file "$2"; fi
exec .venv/Scripts/python.exe -m lead_assistant.mcp_call "$1" "${2:-{\}}"
