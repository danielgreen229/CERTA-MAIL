"""Печатает вызовы инструментов из трейса в виде таблицы.

python scripts/show_trace.py runs/<run_id>/mcp_trace.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    print(
        f"{'#':>3} {'инструмент':<12} {'ID':>5} {'исход':<18} {'категория':<10} {'приоритет':<9} мс"
    )
    number = 0
    for line in Path(argv[0]).read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("event") != "tool_call":
            continue
        number += 1
        if event.get("ok"):
            count = event.get("count")
            outcome = event.get("result") or (f"ok, {count} шт." if count is not None else "ok")
        else:
            outcome = f"ОШИБКА {event.get('code')}"
        lead_id = event.get("lead_id")
        print(
            f"{number:>3} {event.get('tool', ''):<12} {'' if lead_id is None else lead_id!s:>5} "
            f"{outcome:<18} {event.get('category') or '':<10} {event.get('priority') or '':<9} "
            f"{event.get('duration_ms')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
