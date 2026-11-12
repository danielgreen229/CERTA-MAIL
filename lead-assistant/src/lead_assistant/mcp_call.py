"""Ручной вызов инструмента MCP-сервера через stdio — для диагностики.

    python -m lead_assistant.mcp_call list_leads '{"status": "new"}'
    python -m lead_assistant.mcp_call get_lead '{"id": 3}'
    python -m lead_assistant.mcp_call update_lead --args-file args.json
    python -m lead_assistant.mcp_call --list-tools

Сервер запускается так же, как его запускает агент; путь к файлу берётся из LEADS_FILE.
Печатает ответ инструмента; код возврата 1, если инструмент вернул ошибку.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from lead_assistant.agent import mcp_server_command
from lead_assistant.backends import use_utf8_console
from lead_assistant.cli import DEFAULT_LEADS_FILE
from lead_assistant.models import (
    ENV_LEADS_FILE,
    ENV_LOG_LEVEL,
    ENV_RUN_ID,
    ENV_TRACE_FILE,
)


async def call(
    tool: str | None, arguments: dict[str, Any], env: dict[str, str]
) -> tuple[bool, str]:
    from mcp import Client, StdioServerParameters

    command, args = mcp_server_command()
    async with Client(StdioServerParameters(command=command, args=args, env=env)) as client:
        if tool is None:
            tools = await client.list_tools()
            return False, json.dumps(sorted(t.name for t in tools.tools))
        result = await client.call_tool(tool, arguments)
        text = "\n".join(block.text for block in result.content if hasattr(block, "text"))
        return bool(result.is_error), text


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(prog="python -m lead_assistant.mcp_call")
    parser.add_argument("tool", nargs="?", help="list_leads, get_lead или update_lead")
    parser.add_argument("arguments", nargs="?", default="{}", help="аргументы в JSON")
    parser.add_argument("--args-file", help="файл с аргументами в JSON (вместо строки)")
    parser.add_argument("--list-tools", action="store_true")
    parser.add_argument(
        "--leads-file", default=os.environ.get(ENV_LEADS_FILE) or DEFAULT_LEADS_FILE
    )
    args = parser.parse_args(argv)
    if not args.list_tools and not args.tool:
        parser.error("укажите инструмент или --list-tools")
    raw = args.arguments
    if args.args_file:
        with open(args.args_file, encoding="utf-8") as handle:
            raw = handle.read()
    try:
        arguments = json.loads(raw)
    except json.JSONDecodeError as error:
        parser.error(f"аргументы должны быть JSON-объектом: {error}")
    if not isinstance(arguments, dict):
        parser.error("аргументы должны быть JSON-объектом")

    env = {ENV_LEADS_FILE: os.path.abspath(args.leads_file), ENV_LOG_LEVEL: "WARNING"}
    for name in (ENV_TRACE_FILE, ENV_RUN_ID):
        if os.environ.get(name):
            env[name] = os.environ[name]
    is_error, text = asyncio.run(call(None if args.list_tools else args.tool, arguments, env))
    print(text)
    return 1 if is_error else 0


if __name__ == "__main__":
    sys.exit(main())
