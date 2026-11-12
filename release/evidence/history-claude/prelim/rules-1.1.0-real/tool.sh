#!/usr/bin/env bash
# Обёртка трёх MCP-инструментов для предварительной проверки (вызов через stdio).
cd "C:/Users/Dozer/Desktop/work/CERTATZ/TZ/lead-assistant"
export LEADS_FILE="C:\Users\Dozer\Desktop\work\CERTATZ\TZ\lead-assistant\surrogate\real\leads.json"
export LEADS_TRACE_FILE="C:\Users\Dozer\Desktop\work\CERTATZ\TZ\lead-assistant\surrogate\real\runs\20261111T220601Z-a0b7a6\mcp_trace.jsonl"
export LEADS_RUN_ID="20261111T220601Z-a0b7a6"
if [ -f "$2" ]; then exec .venv/Scripts/python.exe -m lead_assistant.mcp_call "$1" --args-file "$2"; fi
exec .venv/Scripts/python.exe -m lead_assistant.mcp_call "$1" "${2:-{\}}"
