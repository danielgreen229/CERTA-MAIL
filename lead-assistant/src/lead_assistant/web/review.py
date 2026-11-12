"""Очередь проверки: почему заявку нужно показать человеку, кому и к какому сроку."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

# Черновик берёт на себя обязательство от имени компании: обещание действия, денег или
# срока, конкретная сумма. Упоминание темы клиента («стоимость», «договор») — не обязательство.
_COMMITMENT = re.compile(
    r"\b(?:мы\s+)?(?:верн[её]м|компенсируем|гарантируем|предоставим|пришл[её]м|отправим|"
    r"доставим|привез[её]м|сделаем|оформим|подпишем|снизим)(?![а-яё])|"
    r"бесплатн\w*|скидк\w*\s+\d|\d[\d\s]*(?:руб\w*|₽|\$|usd|eur)|"
    r"\bwe\s+(?:will|guarantee)\b|\brefund\b|\bdiscount\b",
    re.I,
)


def review_reasons(
    category: str | None,
    priority: str | None,
    draft: str | None,
    analysis: dict[str, Any],
    extraction: dict[str, Any],
) -> list[dict[str, str]]:
    """Причины обязательной проверки человеком. Пустой список — проверка не обязательна."""
    reasons: list[dict[str, str]] = []

    def add(code: str, text: str) -> None:
        reasons.append({"code": code, "text": text})

    if priority == "high":
        basis = analysis.get("urgency_basis")
        add("urgent", f"Срочно: {basis}" if basis else "Срочное обращение")
    if category == "complaint":
        add("complaint", "Жалоба: ответ затрагивает репутацию и возможные компенсации")
    for item in extraction.get("contradictions") or []:
        add("contradiction", f"Противоречие: {item}")
    missing = extraction.get("missing") or []
    # Если черновик сам спрашивает клиента о недостающем, человеку здесь проверять нечего:
    # данные придут в ответ на черновик. Так в очередь проверки не попадают обычные заявки.
    asks_client = bool(draft and "?" in draft)
    if missing and category != "spam" and not asks_client:
        add("insufficient", "Не хватает сведений: " + ", ".join(missing))
    check = analysis.get("manager_check")
    actionable = _actionable_notes(check, category)
    if analysis.get("uncertain") and (actionable or not check):
        add(
            "weak_basis",
            f"Агент не уверен: {' '.join(actionable)}"
            if actionable
            else "Агент отметил случай спорным",
        )
    if draft and _COMMITMENT.search(draft):
        add("commitment", "Черновик касается обязательств компании (деньги, договор, сроки)")
    if category == "spam" and analysis.get("uncertain") and (actionable or not check):
        add("spam_check", "Проверьте, что это действительно спам")
    return reasons


# Пометки, которые полезно видеть в письме, но которые сами по себе не требуют ручной
# проверки: повтор от того же клиента, уже учтённый в срочности истёкший срок, попытка
# управлять помощником в письме, которое и так признано спамом.
_INFORMATIONAL = (
    re.compile(r"^Повтор:"),
    re.compile(r"^Названный в заявке срок уже истёк"),
)
_INJECTION_NOTE = re.compile(r"^Текст пытается управлять помощником")


def _actionable_notes(check: object, category: str | None) -> list[str]:
    """Пометки агента, ради которых письмо стоит показать человеку."""
    if not isinstance(check, str) or not check.strip():
        return []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", check.strip()) if s.strip()]
    kept = []
    for sentence in sentences:
        if any(p.search(sentence) for p in _INFORMATIONAL):
            continue
        if category == "spam" and _INJECTION_NOTE.search(sentence):
            continue
        kept.append(sentence)
    return kept


def _next_work_moment(moment: datetime, settings: dict[str, Any]) -> datetime:
    hours = settings["work_hours"]
    start, end, days = int(hours["start"]), int(hours["end"]), set(hours["days"])
    for _ in range(14):
        day_start = moment.replace(hour=start, minute=0, second=0, microsecond=0)
        day_end = moment.replace(hour=end, minute=0, second=0, microsecond=0)
        if moment.weekday() in days and moment < day_end:
            return max(moment, day_start)
        moment = (moment + timedelta(days=1)).replace(hour=start, minute=0, second=0)
    return moment


def due_at(received: datetime, priority: str | None, settings: dict[str, Any]) -> datetime | None:
    """Срок реакции: часы по приоритету, считаются только в рабочее время календаря."""
    if priority is None:
        return None
    hours = settings["sla_hours"].get(priority)
    if hours is None:
        return None
    tz = ZoneInfo(settings["timezone"])
    moment = _next_work_moment(received.astimezone(tz), settings)
    left = timedelta(hours=float(hours))
    end_hour = int(settings["work_hours"]["end"])
    while left > timedelta(0):
        day_end = moment.replace(hour=end_hour, minute=0, second=0, microsecond=0)
        available = day_end - moment
        if left <= available:
            return moment + left
        left -= available
        moment = _next_work_moment(day_end + timedelta(seconds=1), settings)
    return moment


def default_assignee(category: str | None, settings: dict[str, Any]) -> str | None:
    if category is None:
        return None
    value = settings["assignment"].get(category)
    return str(value) if value else None
