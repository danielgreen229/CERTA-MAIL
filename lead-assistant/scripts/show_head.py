"""Печатает первые N строк текстового файла в UTF-8 независимо от локали консоли.

python scripts/show_head.py FILE [N]
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    limit = int(argv[1]) if len(argv) > 1 else 40
    lines = Path(argv[0]).read_text(encoding="utf-8").splitlines()
    print("\n".join(lines[:limit]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
