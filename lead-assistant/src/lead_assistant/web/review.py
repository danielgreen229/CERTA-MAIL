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
    if missing and category != "spam":
        add("insufficient", "Не хватает сведений: " + ", ".join(missing))
    if analysis.get("uncertain"):
        check = analysis.get("manager_check")
        add("weak_basis", f"Агент не уверен: {check}" if check else "Агент отметил случай спорным")
    if draft and _COMMITMENT.search(draft):
        add("commitment", "Черновик касается обязательств компании (деньги, договор, сроки)")
    if category == "spam" and analysis.get("uncertain"):
        add("spam_check", "Проверьте, что это действительно спам")
    return reasons


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
