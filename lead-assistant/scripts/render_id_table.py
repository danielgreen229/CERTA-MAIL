"""Строит таблицу сверки реальных заявок по ID для отчёта проверки (Markdown).

python scripts/render_id_table.py ORIGINAL PROCESSED RUN_JSON REAL_EVAL_JSON EXPECTATIONS
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__)
        return 2
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    original, processed, run, evaluation, expectations = (_load(path) for path in argv)
    entries = {entry["id"]: entry for entry in run["reconciliation"]["leads"]}
    before = {lead["id"]: lead for lead in original}

    print(
        "| ID | Обращение (исходный текст) | Категория | Приоритет | Эталон | Проверки "
        "| Черновик и пометки |"
    )
    print("|---|---|---|---|---|---|---|")
    for lead in processed:
        lead_id = lead["id"]
        expect = expectations["leads"][str(lead_id)]
        result = evaluation["results"][str(lead_id)]
        failed = [check["name"] for check in result["checks"] if not check["ok"]]
        verdict = "пройдены" if result["ok"] else "не пройдены: " + ", ".join(failed)
        if expect.get("untouched"):
            same = lead == before[lead_id]
            print(
                f"| {lead_id} | {_cell(before[lead_id]['text'])} | {lead.get('category')} | "
                f"{lead.get('priority')} | не трогать | {verdict} | "
                f"запись {'совпадает с оригиналом' if same else 'ИЗМЕНЕНА'} |"
            )
            continue
        entry = entries.get(lead_id, {})
        allowed = f"{'/'.join(expect['category'])}; {'/'.join(expect['priority'])}"
        if expect.get("ambiguous"):
            allowed += " (неоднозначный)"
        draft = lead.get("draft_reply")
        notes = [f"черновик: {_cell(draft)}" if draft else "черновика нет (спам)"]
        if entry.get("urgency_basis"):
            notes.append(f"основание: {_cell(entry['urgency_basis'])}")
        if entry.get("uncertain") and entry.get("manager_check"):
            notes.append(f"менеджеру: {_cell(entry['manager_check'])}")
        print(
            f"| {lead_id} | {_cell(before[lead_id]['text'])} | {lead.get('category')} | "
            f"{lead.get('priority')} | {allowed} | {verdict} | {'<br>'.join(notes)} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
