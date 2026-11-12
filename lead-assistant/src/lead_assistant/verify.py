"""Независимая сверка обработанного файла с оригиналом.

    python -m lead_assistant.verify data/leads.original.json data/leads.json --expect-all-processed

Проверяет порядок и число заявок, неизменность полей вне category/priority/status/
draft_reply, неизменность ранее обработанных записей и корректность записанных значений.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lead_assistant.backends import use_utf8_console
from lead_assistant.models import STATUS_NEW, STATUS_PROCESSED, LeadError
from lead_assistant.reconcile import check_integrity, check_processed_shape, id_key
from lead_assistant.storage import parse_leads, sha256_hex


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(prog="python -m lead_assistant.verify")
    parser.add_argument("original", type=Path)
    parser.add_argument("processed", type=Path)
    parser.add_argument(
        "--expect-all-processed",
        action="store_true",
        help="считать ошибкой любую заявку, оставшуюся в статусе new",
    )
    args = parser.parse_args(argv)

    try:
        original_raw = args.original.read_bytes()
        processed_raw = args.processed.read_bytes()
        original = parse_leads(original_raw)
        processed = parse_leads(processed_raw)
    except (OSError, LeadError) as error:
        print(f"ОШИБКА чтения: {error}")
        return 2

    print(f"оригинал : {args.original}  sha256={sha256_hex(original_raw)}")
    print(f"результат: {args.processed}  sha256={sha256_hex(processed_raw)}")

    scope = [lead["id"] for lead in original if lead["status"] == STATUS_NEW]
    problems = check_integrity(original, processed, scope)
    after = {id_key(lead["id"]): lead for lead in processed}

    print(f"{'ID':>4}  {'было':<10} {'стало':<10} {'категория':<10} {'приоритет':<9} черновик")
    for lead in original:
        current = after.get(id_key(lead["id"]))
        if current is None:
            continue
        draft = current.get("draft_reply", "—")
        draft_note = (
            "null" if draft is None else (f"{len(draft)} симв." if isinstance(draft, str) else "—")
        )
        print(
            f"{lead['id']!s:>4}  {lead['status']:<10} {current['status']:<10} "
            f"{current.get('category') or '—'!s:<10} "
            f"{current.get('priority') or '—'!s:<9} {draft_note}"
        )
        if current["status"] == STATUS_PROCESSED and lead["status"] == STATUS_NEW:
            problems.extend(check_processed_shape(current))

    remaining = [lead["id"] for lead in processed if lead["status"] == STATUS_NEW]
    untouched = [
        x["id"] for x in original if x["status"] != STATUS_NEW and after.get(id_key(x["id"])) == x
    ]
    print(f"исходных new: {len(scope)}; осталось new: {len(remaining)} {remaining or ''}")
    print(f"ранее обработанные без изменений: {untouched}")
    if args.expect_all_processed and remaining:
        problems.append(f"REMAINING_NEW: {remaining}")
    if problems:
        print("НАРУШЕНИЯ:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("сверка пройдена: данные сохранены, изменены только разрешённые поля")
    return 0


if __name__ == "__main__":
    sys.exit(main())
