#!/usr/bin/env bash
# Открывает Claude Code в рабочем режиме помощника: модели доступны только три
# MCP-инструмента проекта. В сессии введите «обработай новые заявки» или /process-leads.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec claude \
  --tools "" \
  --strict-mcp-config --mcp-config .mcp.json \
  --allowedTools "mcp__leads__list_leads,mcp__leads__get_lead,mcp__leads__update_lead" \
  "$@"
