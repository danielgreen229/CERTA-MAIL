"""Сводка руководителю. Числа берутся из сверки файла, пояснения — из итога модели."""

from __future__ import annotations

from typing import Any

_STATUS_TEXT = {
    "ok": "выполнен без замечаний",
    "ok_with_warnings": "выполнен, есть предупреждения",
    "incomplete": "выполнен не полностью — требуется внимание",
    "failed": "не выполнен",
}
_NO_EXPLANATION = "пояснение модели недоступно — откройте заявку"


def _sentence(text: object) -> str:
    """Пояснение одной фразой с ровно одной точкой в конце."""
    value = str(text).strip() if text else _NO_EXPLANATION
    return value.rstrip(". ") + "."


def _ids(values: list[Any]) -> str:
    return ", ".join(str(value) for value in values) if values else "—"


def _counter(values: dict[str, int], order: tuple[str, ...]) -> str:
    parts = [f"{name} — {values[name]}" for name in order if values.get(name)]
    return ", ".join(parts) if parts else "—"


def render_summary(run: dict[str, Any]) -> str:
    """Строит короткую сводку в Markdown по структурированному итогу прогона."""
    rec = run["reconciliation"]
    counts = rec["counts"]
    leads = rec["leads"]
    lines = [
        "# Сводка обработки заявок",
        "",
        f"Прогон `{run['run_id']}` · дата {run['today']} · модель "
        f"{run['runtime'].get('model') or 'не вызывалась'} · правила {run['rules']['version']}",
        f"Статус: **{_STATUS_TEXT[run['status']]}**",
        "",
        "## Итог",
        "",
        f"- Найдено новых: {counts['found']} (ID: {_ids(rec['found_ids'])})",
        f"- Записано: {counts['written']}",
        f"- Уже были обработаны: {counts['already_processed']}"
        + (f" (ID: {_ids(rec['already_processed_ids'])})" if rec["already_processed_ids"] else ""),
        f"- Ошибки: {counts['failed']}",
        f"- Осталось `new` в файле: {len(rec['remaining_new_ids'])}"
        + (f" (ID: {_ids(rec['remaining_new_ids'])})" if rec["remaining_new_ids"] else ""),
        "- По категориям: "
        + _counter(rec["by_category"], ("sale", "complaint", "question", "spam")),
        "- По приоритетам: " + _counter(rec["by_priority"], ("high", "medium", "low")),
    ]

    high = [e for e in leads if e.get("priority") == "high" and e["result"] == "written"]
    lines += ["", "## Срочные (high)", ""]
    if high:
        for entry in high:
            lines.append(
                f"- **ID {entry['id']}** ({entry['category']}). "
                f"Основание: {_sentence(entry.get('urgency_basis'))} "
                f"Действие: {_sentence(entry.get('next_action'))}"
            )
    else:
        lines.append("Нет.")

    flagged = [e for e in leads if e.get("uncertain")]
    lines += ["", "## Проверить менеджеру", ""]
    if flagged:
        for entry in flagged:
            lines.append(f"- **ID {entry['id']}**: {entry.get('manager_check') or _NO_EXPLANATION}")
    elif not rec["model_report_available"] and counts["found"]:
        lines.append("Итог модели не получен: спорные случаи не размечены, проверьте черновики.")
    else:
        lines.append("Нет.")

    spam = [e["id"] for e in leads if e.get("category") == "spam" and e["result"] == "written"]
    if spam:
        lines += [
            "",
            "## Спам (без черновика)",
            "",
            f"ID: {_ids(spam)}. Просмотрите список: если среди них настоящий клиент, "
            "ответьте ему вручную.",
        ]

    problems = (
        [f"заявка {f['id']}: {f['reason']}" for f in rec["failed"]]
        + rec["integrity_violations"]
        + rec["report_mismatches"]
        + rec["warnings"]
    )
    if run.get("error"):
        problems.insert(0, f"{run['error']['code']}: {run['error'].get('message') or ''}".strip())
    if problems:
        lines += ["", "## Ошибки и предупреждения", ""]
        lines += [f"- {problem}" for problem in problems]

    if leads:
        lines += [
            "",
            "## Заявки",
            "",
            "| ID | Категория | Приоритет | Результат |",
            "|---|---|---|---|",
        ]
        for entry in leads:
            lines.append(
                f"| {entry['id']} | {entry.get('category') or '—'} | "
                f"{entry.get('priority') or '—'} | {entry['result']} |"
            )

    lines += [
        "",
        "Черновики лежат в поле `draft_reply` файла заявок. Ответы клиентам отправляет "
        "менеджер после проверки.",
        "",
    ]
    return "\n".join(lines)
