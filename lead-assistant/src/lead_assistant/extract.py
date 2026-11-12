"""Логистический разбор обращения: извлечение сведений, противоречия, недостаток данных.

Разбор детерминированный (правила и регулярные выражения), поэтому одинаково работает
для любой модели и проверяется тестами. Каждое найденное значение хранит дословный
фрагмент текста, из которого оно взято. Отсутствующие сведения возвращаются явно
со значением ``None``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

MONTHS = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}
WEEKDAYS = {
    "понедельник": 0,
    "вторник": 1,
    "сред": 2,
    "четверг": 3,
    "пятниц": 4,
    "суббот": 5,
    "воскресень": 6,
}
FIELD_TITLES = {
    "route": "Маршрут",
    "cargo": "Груз",
    "weight": "Вес",
    "volume": "Объём",
    "transport": "Вид перевозки",
    "dates": "Даты",
    "order": "Номер заказа или отправления",
    "contact_person": "Контактное лицо",
}

_CITY = r"[А-ЯЁ][а-яё]+(?:[- ][А-ЯЁ][а-яё]+)?"
_ROUTE_PATTERNS = (
    re.compile(rf"\bиз\s+(?P<a>{_CITY})\s+(?:в|до|на)\s+(?P<b>{_CITY})"),
    re.compile(rf"\b(?P<a>{_CITY})\s*[—–-]\s*(?P<b>{_CITY})\b"),
    re.compile(r"\bfrom\s+(?P<a>[A-Z][a-z]+)\s+to\s+(?P<b>[A-Z][a-z]+)"),
)
_DEST = re.compile(rf"\b(?:доставк\w*|перевозк\w*|отправк\w*|груз\w*)\s+(?:в|до)\s+(?P<b>{_CITY})")
_NUMBER = r"\d+(?:[.,]\d+)?"
_WEIGHT = re.compile(rf"(?P<n>{_NUMBER})\s*(?P<u>тонн\w*|т\b|кг\b|килограмм\w*)", re.I)
_VOLUME = re.compile(rf"(?P<n>{_NUMBER})\s*(?P<u>м3|м³|куб\.?\s*м|кубометр\w*|куб\w*)", re.I)
_PACKAGES = re.compile(
    rf"(?P<n>{_NUMBER}|two|three|four|five|ten)\s*(?:x\s*)?(?:\d+\s*(?:ft|футов\w*)\s*)?"
    r"(?P<u>паллет\w*|паллетомест\w*|коробк\w*|короб\w*|мест[ао]?\b|контейнер\w*|"
    r"ящик\w*|рулон\w*|containers?|pallets?|boxes)"
    r"(?P<what>(?:\s+[а-яё]{3,}){0,2})",
    re.I,
)
# Описание груза после веса: «2 тонн плитки».
_AFTER_WEIGHT = re.compile(r"^\s+(?P<what>[а-яё]{3,}(?:\s+[а-яё]{3,})?)", re.I)
_CARGO = re.compile(r"\bгруз\s*:\s*(?P<c>[^.,;!?\n]{3,60})", re.I)
_STOP_WORDS = {"из", "в", "до", "на", "по", "для", "от", "через", "внутри", "раздавлены"}
_TRANSPORT = (
    ("авиа", re.compile(r"\bавиа\w*|самолет\w*|самолёт\w*", re.I)),
    ("ж/д", re.compile(r"\bж/д\b|железнодорожн\w*|вагон\w*", re.I)),
    ("морская", re.compile(r"\bморск\w*|судн\w*|фрахт\w*", re.I)),
    ("авто", re.compile(r"\bфур\w*|автомобил\w*|машин\w*|грузовик\w*|авто\b", re.I)),
)
_ORDER = re.compile(
    r"(?P<kind>заказ\w*|накладн\w*|отправлени\w*|трек\w*)\s*(?:№|N|#|номер)?\s*(?P<n>\d{3,})",
    re.I,
)
_HASH_NUMBER = re.compile(r"№\s*(?P<n>\d{3,})")
_DATE_DM = re.compile(r"\b(?P<d>\d{1,2})\s+(?P<m>[а-яё]+)\b", re.I)
_DATE_NUMERIC = re.compile(r"\b(?P<d>\d{1,2})\.(?P<m>\d{1,2})(?:\.(?P<y>\d{2,4}))?\b")
_DATE_ISO = re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b")
_RELATIVE = (
    ("сегодня", 0),
    ("послезавтра", 2),
    ("завтра", 1),
)
_WEEKDAY = re.compile(
    r"\b(?:в|до|к|на)\s+(?P<w>понедельник|вторник|сред\w*|четверг\w*|пятниц\w*|"
    r"суббот\w*|воскресень\w*)",
    re.I,
)
_THIS_WEEK = re.compile(r"на\s+этой\s+неделе", re.I)
_CONTACT_PERSON = re.compile(
    r"контактн\w*\s+лиц\w*[:\s—-]+(?P<p>[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)"
)


@dataclass
class Found:
    value: Any
    quote: str

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "quote": self.quote}


@dataclass
class Extraction:
    fields: dict[str, list[Found]] = field(default_factory=dict)
    contradictions: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fields": {
                name: [item.to_dict() for item in self.fields.get(name, [])] or None
                for name in FIELD_TITLES
            },
            "contradictions": self.contradictions,
            "missing": self.missing,
        }


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def _unit_weight(unit: str) -> tuple[str, float]:
    unit = unit.lower()
    if unit.startswith(("кг", "килограмм")):
        return "кг", 1.0
    return "т", 1000.0


def _resolve_dm(day: int, month: int, base: date) -> date | None:
    try:
        candidate = date(base.year, month, day)
    except ValueError:
        return None
    # Дата без года: ближайшая к дате сообщения (декабрь → январь следующего года).
    if (base - candidate).days > 180:
        candidate = candidate.replace(year=base.year + 1)
    return candidate


def _month(word: str) -> int | None:
    word = word.lower()
    for stem, number in MONTHS.items():
        if word.startswith(stem) and (stem != "ма" or word in ("мая", "май", "мае")):
            return number
    return None


def extract_dates(text: str, base: date) -> list[Found]:
    found: list[Found] = []
    for match in _DATE_ISO.finditer(text):
        try:
            value = date(int(match["y"]), int(match["m"]), int(match["d"]))
        except ValueError:
            continue
        found.append(Found(value.isoformat(), match.group(0)))
    for match in _DATE_DM.finditer(text):
        month = _month(match["m"])
        if month is None:
            continue
        resolved = _resolve_dm(int(match["d"]), month, base)
        if resolved:
            found.append(Found(resolved.isoformat(), match.group(0)))
    for match in _DATE_NUMERIC.finditer(text):
        day, month = int(match["d"]), int(match["m"])
        if not (1 <= month <= 12):
            continue
        resolved = _resolve_dm(day, month, base)
        if resolved:
            if match["y"]:
                year = int(match["y"])
                year = year + 2000 if year < 100 else year
                try:
                    resolved = resolved.replace(year=year)
                except ValueError:
                    continue
            found.append(Found(resolved.isoformat(), match.group(0)))
    lowered = text.lower()
    for word, offset in _RELATIVE:
        position = lowered.find(word)
        if position >= 0 and not (word == "завтра" and "послезавтра" in lowered):
            found.append(Found((base + timedelta(days=offset)).isoformat(), word))
    for match in _WEEKDAY.finditer(text):
        target = next(v for k, v in WEEKDAYS.items() if match["w"].lower().startswith(k))
        ahead = (target - base.weekday()) % 7 or 7
        found.append(Found((base + timedelta(days=ahead)).isoformat(), match.group(0)))
    week = _THIS_WEEK.search(text)
    if week:
        end = base + timedelta(days=6 - base.weekday())
        found.append(Found(end.isoformat(), week.group(0)))
    unique: dict[str, Found] = {}
    for item in found:
        unique.setdefault(f"{item.value}|{item.quote}", item)
    return sorted(unique.values(), key=lambda item: str(item.value))


def extract(lead: dict[str, Any], base: date | None = None) -> Extraction:
    """Извлекает сведения из текста заявки; даты считаются от даты сообщения."""
    text = str(lead.get("text") or "")
    message_date = base or _lead_date(lead) or date.today()
    result = Extraction()

    routes: list[Found] = []
    for pattern in _ROUTE_PATTERNS:
        for match in pattern.finditer(text):
            routes.append(Found({"from": match["a"], "to": match["b"]}, match.group(0)))
    if not routes:
        for match in _DEST.finditer(text):
            routes.append(Found({"from": None, "to": match["b"]}, match.group(0)))
    result.fields["route"] = routes

    weights = []
    for match in _WEIGHT.finditer(text):
        unit, factor = _unit_weight(match["u"])
        weights.append(
            Found(
                {"amount": _num(match["n"]), "unit": unit, "kg": _num(match["n"]) * factor},
                match.group(0),
            )
        )
    result.fields["weight"] = weights
    result.fields["volume"] = [
        Found({"amount": _num(m["n"]), "unit": "м³"}, m.group(0)) for m in _VOLUME.finditer(text)
    ]
    cargo: list[Found] = []
    for match in _PACKAGES.finditer(text):
        what = " ".join(w for w in match["what"].split() if w.lower() not in _STOP_WORDS)
        label = f"{match['n']} {match['u']}" + (f" {what}" if what else "")
        cargo.append(Found(label, match.group(0).strip()))
    for match in _WEIGHT.finditer(text):
        tail = _AFTER_WEIGHT.match(text[match.end() :])
        if tail and tail["what"].split()[0].lower() not in _STOP_WORDS:
            cargo.append(Found(tail["what"], (match.group(0) + tail.group(0)).strip()))
    cargo += [Found(m["c"].strip(), m.group(0).strip()) for m in _CARGO.finditer(text)]
    result.fields["cargo"] = cargo
    result.fields["transport"] = [
        Found(name, hit.group(0))
        for name, pattern in _TRANSPORT
        if (hit := pattern.search(text)) is not None
    ]
    result.fields["dates"] = extract_dates(text, message_date)
    orders = [
        Found({"kind": _order_kind(m["kind"]), "number": m["n"]}, m.group(0))
        for m in _ORDER.finditer(text)
    ]
    known = {o.value["number"] for o in orders}
    orders += [
        Found({"kind": "номер", "number": m["n"]}, m.group(0))
        for m in _HASH_NUMBER.finditer(text)
        if m["n"] not in known
    ]
    result.fields["order"] = orders
    persons = [Found(m["p"], m.group(0)) for m in _CONTACT_PERSON.finditer(text)]
    name = str(lead.get("name") or "").strip()
    if not persons and name and _looks_like_person(name):
        persons.append(Found(name, f"поле «имя»: {name}"))
    result.fields["contact_person"] = persons

    _contradictions(result)
    return result


def _order_kind(word: str) -> str:
    word = word.lower()
    if word.startswith("накладн"):
        return "накладная"
    if word.startswith(("отправлен", "трек")):
        return "отправление"
    return "заказ"


def _looks_like_person(name: str) -> bool:
    lowered = name.lower()
    if any(token in lowered for token in ("гость", "guest", "admin", "user", "@", "http")):
        return False
    return bool(re.fullmatch(r"[A-Za-zА-ЯЁа-яё][A-Za-zА-ЯЁа-яё.\- ]{1,60}", name))


def _lead_date(lead: dict[str, Any]) -> date | None:
    value = lead.get("date")
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _contradictions(result: Extraction) -> None:
    weights = {round(item.value["kg"], 3) for item in result.fields["weight"]}
    if len(weights) > 1:
        quotes = ", ".join(f"«{item.quote}»" for item in result.fields["weight"])
        result.contradictions.append(f"Указано несколько разных значений веса: {quotes}")
    routes = {(r.value.get("from"), r.value.get("to")) for r in result.fields["route"]}
    destinations = {to for _, to in routes if to}
    if len(destinations) > 1:
        quotes = ", ".join(f"«{item.quote}»" for item in result.fields["route"])
        result.contradictions.append(f"Названо несколько пунктов назначения: {quotes}")


def missing_for(category: str | None, result: Extraction, lead: dict[str, Any]) -> list[str]:
    """Каких сведений не хватает для содержательной работы по заявке этой категории."""
    missing: list[str] = []
    if category == "sale":
        if not result.fields.get("route"):
            missing.append("маршрут (откуда и куда)")
        if not result.fields.get("weight") and not result.fields.get("volume"):
            missing.append("вес или объём груза")
        if not result.fields.get("cargo"):
            missing.append("описание груза")
        if not result.fields.get("dates"):
            missing.append("желаемые даты")
    if category == "complaint" and not result.fields.get("order"):
        missing.append("номер заказа или отправления")
    if category != "spam" and not str(lead.get("contact") or "").strip():
        missing.append("контакт для ответа")
    return missing
