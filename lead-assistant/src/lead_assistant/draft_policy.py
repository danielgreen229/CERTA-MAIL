"""Проверка черновика ответа на утверждения, которых нет в заявке.

У помощника нет источника сведений о компании: тарифов, сроков, статусов, условий.
Поэтому черновик не может утверждать ничего от имени компании. Проверка
детерминированная и намеренно узкая — она ловит типовые формулировки, а не заменяет
менеджера:

* утверждения о возможностях и условиях компании («мы работаем с…», «мы доставляем…»);
* сообщения о действиях, которые якобы уже выполнены или идут («уже проверяем»);
* обещания возврата, компенсации, скидки и гарантии;
* числа, которых нет в заявке (выдуманные цены, сроки, проценты).

Проверка выполняется сервером при записи (update_lead) и при оценке результата.
"""

from __future__ import annotations

import re
from typing import Any

from lead_assistant.models import EDITABLE_FIELDS

_FLAGS = re.IGNORECASE | re.UNICODE

# (описание для сообщения об ошибке, шаблон)
_PHRASES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "утверждение о возможностях или условиях компании",
        re.compile(
            r"\b(мы|наша компания)\s+(уже\s+|также\s+|действительно\s+)?"
            r"(работаем|работает|предоставляем|предоставляет|доставляем|доставляет|"
            r"осуществляем|осуществляет|перевозим|перевозит|возим|принимаем|оказываем|"
            r"обеспечиваем|сотрудничаем)\b",
            _FLAGS,
        ),
    ),
    (
        "утверждение о возможностях или условиях компании",
        re.compile(
            r"\b(we|our company)\s+(do\s+|also\s+|already\s+)?"
            r"(work|works|deliver|delivers|ship|ships|provide|provides|offer|offers|operate|"
            r"operates|accept|accepts|cooperate)\b",
            _FLAGS,
        ),
    ),
    (
        "сообщение о действии, которое якобы уже выполнено или выполняется",
        re.compile(
            r"\bуже\s+(проверяем|проверили|занимаемся|решаем|разбираемся|рассматриваем|"
            r"отправили|выслали|вернули|передали|связались|назначили|оформили|готовим|"
            r"подготовили|работаем)\b",
            _FLAGS,
        ),
    ),
    (
        "сообщение о действии, которое якобы уже выполнено или выполняется",
        re.compile(
            r"\b(договор|документ\w*|деньги|средства|груз|заказ|встреча)\s+(уже\s+)?"
            r"(отправлен\w*|выслан\w*|возвращен\w*|возвращён\w*|доставлен\w*|назначен\w*|"
            r"перенесен\w*|перенесён\w*)\b",
            _FLAGS,
        ),
    ),
    (
        "сообщение о действии, которое якобы уже выполнено или выполняется",
        re.compile(
            r"\bwe\s+(are|have)\s+(already\s+|currently\s+|now\s+)?"
            r"(checking|processing|reviewing|investigating|working|sent|shipped|refunded|"
            r"scheduled|prepared)\b",
            _FLAGS,
        ),
    ),
    (
        "обещание от имени компании",
        re.compile(
            r"\b(гарантируем|гарантирует|обещаем|обещает|верн[её]м|верн[её]т|возместим|"
            r"возместит|компенсируем|компенсирует|оплатим|оплатит|предоставим скидку|"
            r"предоставит скидку|сделаем скидку|сделает скидку)\b|\bбесплатн\w+",
            _FLAGS,
        ),
    ),
    (
        "обещание от имени компании",
        re.compile(
            r"\bwe\s+(will\s+)?(guarantee|refund|compensate|reimburse)\b|\bfree of charge\b", _FLAGS
        ),
    ),
    (
        "обещание от имени компании",
        re.compile(r"\bположена\s+скидк\w+|\bскидк\w+\s+(в\s+)?\d+\s?%", _FLAGS),
    ),
    (
        "пересказ указаний, адресованных помощнику",
        re.compile(
            r"\bинструкци\w+|\bприоритет\w*\s+(high|medium|low|высок\w+)|\bстатус\w*\s+vip\b|"
            r"\bignore\s+(all\s+)?(previous|prior)\b|\bsystem prompt\b|\bupdate_lead\b",
            _FLAGS,
        ),
    ),
    (
        "просьба подождать вместо действия",
        re.compile(r"\bпроявит\w*\s+терпени\w+|\bнаберит\w*\s+терпени\w+", _FLAGS),
    ),
)

# Число с единицей измерения или из двух и более цифр: цена, срок, процент, дата, номер.
# Дата (05.11.2026, 05/11, 05.11) раскладывается на части; «2,5» и «2.5» — десятичное число.
_DATE = re.compile(
    r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{2,4})(?!\d)|(?<!\d)(\d{1,2})[./](\d{2})(?!\d)"
)
_DECIMAL = re.compile(r"\d+[.,]\d+")
_INTEGER = re.compile(r"\d+")


def _numbers(text: str) -> set[str]:
    """Числа текста в нормальном виде: целые без ведущих нулей, десятичные через точку."""
    found: set[str] = set()

    def take_date(match: re.Match[str]) -> str:
        found.update(part.lstrip("0") or "0" for part in match.groups() if part)
        return " "

    def take_decimal(match: re.Match[str]) -> str:
        found.add(match.group(0).replace(",", "."))
        return " "

    rest = _DECIMAL.sub(take_decimal, _DATE.sub(take_date, text))
    found.update(number.lstrip("0") or "0" for number in _INTEGER.findall(rest))
    return found


def lead_numbers(lead: dict[str, Any]) -> set[str]:
    """Все числа, встречающиеся в полях заявки."""
    found: set[str] = set()
    for key, value in lead.items():
        if key in EDITABLE_FIELDS:
            continue  # результат обработки (в том числе сам черновик) источником фактов не служит
        if isinstance(value, str | int | float) and not isinstance(value, bool):
            found |= _numbers(str(value))
    return found


def detect_language(text: str) -> str:
    """Определяет язык по доле кириллицы и латиницы среди букв."""
    cyrillic = sum(1 for ch in text if "а" <= ch.lower() <= "я" or ch.lower() == "ё")
    latin = sum(1 for ch in text if "a" <= ch.lower() <= "z")
    letters = cyrillic + latin
    if letters == 0:
        return "other"
    if cyrillic / letters >= 0.6:
        return "ru"
    if latin / letters >= 0.6:
        return "en"
    return "mixed"


_LANGUAGE_NAMES = {"ru": "русском", "en": "английском"}


def check_draft(draft: str, lead: dict[str, Any]) -> list[str]:
    """Возвращает нарушения. Пустой список — черновик можно записывать."""
    problems: list[str] = []
    source = str(lead.get("text") or "")
    # По короткому тексту язык не определить надёжно: проверка языка применяется от 20 букв.
    expected = detect_language(source) if sum(ch.isalpha() for ch in source) >= 20 else "other"
    if expected in _LANGUAGE_NAMES and detect_language(draft) != expected:
        problems.append(f"черновик должен быть на языке заявки — на {_LANGUAGE_NAMES[expected]}")
    seen: set[str] = set()
    for description, pattern in _PHRASES:
        match = pattern.search(draft)
        if match and description not in seen:
            seen.add(description)
            problems.append(f"{description}: «{match.group(0)}»")
    known = lead_numbers(lead)
    invented = sorted(
        number
        for number in _numbers(draft)
        if number not in known and (len(number.replace(".", "")) >= 2 or "." in number)
    )
    if invented:
        problems.append(f"числа, которых нет в заявке: {', '.join(invented)}")
    return problems
