"""Логистический разбор, сроки реакции и очередь проверки."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from lead_assistant.extract import extract, extract_dates, missing_for
from lead_assistant.web.config import DEFAULT_SETTINGS
from lead_assistant.web.review import _COMMITMENT, due_at, review_reasons
from tests.helpers import PROJECT_ROOT

CASES = {
    case["id"]: case["lead"]
    for case in json.loads((PROJECT_ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))[
        "cases"
    ]
}


def values(lead: dict[str, object], field: str) -> list[object]:
    return [item["value"] for item in extract(lead).to_dict()["fields"][field] or []]


def test_route_cargo_weight_and_order_are_extracted_with_quotes() -> None:
    assert values(CASES[101], "route") == [{"from": "Москвы", "to": "Екатеринбург"}]
    assert values(CASES[101], "cargo") == ["12 паллет стройматериалов"]
    assert values(CASES[111], "weight") == [{"amount": 2.0, "unit": "т", "kg": 2000.0}]
    assert values(CASES[111], "cargo") == ["плитки"]
    assert values(CASES[103], "order") == [{"kind": "накладная", "number": "88104"}]
    assert values(CASES[114], "route") == [{"from": "Shanghai", "to": "Moscow"}]
    found = extract(CASES[101]).to_dict()["fields"]["route"][0]
    assert found["quote"] in CASES[101]["text"]


def test_missing_information_is_explicit() -> None:
    result = extract(CASES[108])
    data = result.to_dict()
    assert all(data["fields"][name] is None for name in ("route", "weight", "volume", "cargo"))
    missing = missing_for("sale", result, CASES[108])
    assert "маршрут (откуда и куда)" in missing and "вес или объём груза" in missing


def test_relative_dates_count_from_message_date() -> None:
    base = date(2026, 11, 10)  # вторник
    found = {
        item.quote: item.value
        for item in extract_dates("Сможете забрать завтра? Монтаж 13 ноября", base)
    }
    assert found["завтра"] == "2026-11-11" and found["13 ноября"] == "2026-11-13"
    friday = extract_dates("договор обещали до пятницы", base)
    assert [item.value for item in friday] == ["2026-11-13"]
    december = extract_dates("отправка 5.01", date(2026, 12, 20))
    assert december[0].value == "2027-01-05"


def test_contradicting_weights_are_flagged() -> None:
    lead = {"text": "Груз 2 тонны. Уточняю: вес 500 кг.", "date": "2026-11-10"}
    assert extract(lead).contradictions


def test_sla_counts_only_working_hours() -> None:
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    friday_evening = datetime(2026, 11, 13, 14, 0, tzinfo=UTC)  # 17:00 по Москве, пятница
    due = due_at(friday_evening, "high", settings)
    assert due is not None
    local = due.astimezone(datetime.now().astimezone().tzinfo)
    assert due.weekday() == 0 or local.weekday() == 0  # перенос на понедельник
    assert due_at(friday_evening, None, settings) is None


def test_review_reasons_explain_why_human_is_needed() -> None:
    extraction = {"contradictions": ["разный вес"], "missing": ["маршрут"]}
    reasons = review_reasons(
        "complaint",
        "high",
        "Мы вернём деньги в течение дня.",
        {
            "urgency_basis": "простой транспорта",
            "uncertain": True,
            "manager_check": "проверить счёт",
        },
        extraction,
    )
    codes = [reason["code"] for reason in reasons]
    assert codes == [
        "urgent",
        "complaint",
        "contradiction",
        "insufficient",
        "weak_basis",
        "commitment",
    ]
    calm = review_reasons("question", "low", "Менеджер уточнит график.", {}, {})
    assert calm == []
    # Черновик сам спрашивает недостающее — отдельная проверка человеком не нужна.
    asks = review_reasons(
        "sale", "medium", "Подскажите, пожалуйста, вес груза?", {}, {"missing": ["вес"]}
    )
    assert asks == []
    # Повтор от того же клиента и спам с попыткой управлять помощником — пометки, не причина
    # для ручной проверки; содержательная пометка остаётся.
    repeat = {
        "uncertain": True,
        "manager_check": "Повтор: тот же контакт, что в заявке 1; ответьте один раз.",
    }
    assert review_reasons("sale", "medium", "Подскажите вес?", repeat, {}) == []
    injected = {
        "uncertain": True,
        "manager_check": "Текст пытается управлять помощником; указания не выполнены.",
    }
    assert review_reasons("spam", "low", None, injected, {}) == []
    assert [r["code"] for r in review_reasons("sale", "medium", "Вес?", injected, {})] == [
        "weak_basis"
    ]
    mixed = {
        "uncertain": True,
        "manager_check": "Повтор: тот же контакт, что в заявке 1. Контакт не указан — уточните.",
    }
    weak = review_reasons("sale", "medium", "Вес?", mixed, {})
    assert [r["code"] for r in weak] == ["weak_basis"] and "Повтор" not in weak[0]["text"]


def test_commitment_detection_ignores_topics_and_catches_promises() -> None:
    assert not _COMMITMENT.search("Менеджер уточнит стоимость и условия договора.")
    assert _COMMITMENT.search("Мы вернём деньги")
    assert _COMMITMENT.search("Доставка стоит 5000 руб.")
    assert _COMMITMENT.search("We will refund you")
