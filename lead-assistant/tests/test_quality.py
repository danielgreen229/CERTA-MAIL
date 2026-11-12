"""Набор для оценки, эталон по реальным заявкам и функции проверки результата."""

from __future__ import annotations

import json
import re
from typing import Any

from lead_assistant.draft_policy import detect_language
from lead_assistant.evals import SENTINEL, build_fixture
from lead_assistant.models import CATEGORIES, PRIORITIES
from lead_assistant.scoring import asks_for_details, score_lead, summarize
from lead_assistant.storage import FileStyle, parse_leads, serialize_leads
from tests.helpers import ORIGINAL, PROJECT_ROOT

CASES = json.loads((PROJECT_ROOT / "evals" / "cases.json").read_text("utf-8"))
REAL = json.loads((PROJECT_ROOT / "evals" / "real_expectations.json").read_text("utf-8"))

REQUIRED_TAGS = {
    "complaint-as-question",
    "real-deadline",
    "emotional-no-urgency",
    "insufficient-data",
    "spam",
    "injection-inside-lead",
    "injection-tools",
}


def failed(result: dict[str, Any]) -> list[str]:
    return [check["name"] for check in result["checks"] if not check["ok"]]


def test_synthetic_set_covers_required_situations() -> None:
    cases = CASES["cases"]
    assert len({case["id"] for case in cases}) == len(cases) >= 12
    tags = {tag for case in cases for tag in case["tags"]}
    assert tags >= REQUIRED_TAGS
    # Каждая категория и каждый приоритет хотя бы раз ожидаются однозначно.
    for name, values in (("category", CATEGORIES), ("priority", PRIORITIES)):
        unambiguous = {case["expect"][name][0] for case in cases if len(case["expect"][name]) == 1}
        assert unambiguous == set(values)
    for case in cases:
        assert set(case["expect"]["category"]) <= set(CATEGORIES)
        assert set(case["expect"]["priority"]) <= set(PRIORITIES)
        for pattern in case["expect"].get("draft", {}).get("must_not_match", []):
            re.compile(pattern)
        if case["expect"]["category"] == ["spam"]:
            assert case["expect"]["draft"] == {"null": True}


def test_fixture_is_valid_storage_content() -> None:
    fixture = build_fixture(CASES["cases"])
    parsed = parse_leads(serialize_leads(fixture, FileStyle()))
    assert len(parsed) == len(CASES["cases"]) + 1
    assert parsed[-1] == SENTINEL and parsed[0]["status"] == "new"


def test_real_expectations_cover_every_original_lead() -> None:
    original = parse_leads(ORIGINAL.read_bytes())
    assert sorted(REAL["leads"], key=int) == [str(lead["id"]) for lead in original]
    for lead in original:
        expect = REAL["leads"][str(lead["id"])]
        assert expect["rationale"]
        if lead["status"] == "processed":
            assert expect.get("untouched") is True
        else:
            assert expect["category"] and expect["priority"]
            for pattern in expect.get("draft", {}).get("must_not_match", []):
                re.compile(pattern)


def test_detect_language() -> None:
    assert detect_language("Здравствуйте! Уточните маршрут, пожалуйста.") == "ru"
    assert detect_language("Hello, could you share the route details?") == "en"
    assert (
        detect_language("Здравствуйте, Li Wei! Спасибо за обращение по контейнерам 40ft.") == "ru"
    )
    assert detect_language("12345 !!!") == "other"


def test_score_lead_accepts_good_result() -> None:
    lead = {
        "id": 1, "status": "processed", "category": "sale", "priority": "medium",
        "draft_reply": "Здравствуйте! Уточните, пожалуйста, вес и объём груза?",
    }  # fmt: skip
    expect = {
        "category": ["sale"], "priority": ["medium"],
        "draft": {"language": "ru", "needs_question": True, "must_not_match": ["\\d+ руб"]},
    }  # fmt: skip
    assert score_lead(lead, expect)["ok"]


def test_score_lead_reports_each_problem() -> None:
    lead = {
        "id": 1, "status": "processed", "category": "question", "priority": "high",
        "draft_reply": "Доставка стоит 5000 руб. и займёт 2 дня.",
    }  # fmt: skip
    expect = {
        "category": ["sale"], "priority": ["medium"], "flagged": True,
        "draft": {"language": "en", "needs_question": True, "must_not_match": ["\\d+ руб"]},
    }  # fmt: skip
    result = score_lead(lead, expect, {"uncertain": False, "urgency_basis": None})
    assert failed(result) == [
        "category", "priority", "draft_language", "clarifying_question", "draft_policy",
        "no_unsupported_claims", "flagged_for_manager", "high_has_basis",
    ]  # fmt: skip
    assert not result["ok"]


def test_score_lead_spam_and_untouched_and_missing() -> None:
    spam = {
        "id": 3,
        "status": "processed",
        "category": "spam",
        "priority": "low",
        "draft_reply": None,
    }
    assert score_lead(spam, {"category": ["spam"], "priority": ["low"], "draft": {"null": True}})[
        "ok"
    ]
    assert failed(score_lead({**spam, "draft_reply": "x"}, {"draft": {"null": True}})) == [
        "draft_null"
    ]
    # Заявка, признанная спамом там, где допустим и спам, и вопрос.
    assert score_lead(
        spam, {"category": ["spam", "question"], "draft": {"allow_null": True, "language": "ru"}}
    )["ok"]
    assert failed(score_lead({"id": 1, "status": "new"}, {"category": ["sale"]})) == [
        "processed", "category", "draft_present",
    ]  # fmt: skip
    assert score_lead({"id": 15, "a": 1}, {"untouched": True}, None, {"id": 15, "a": 1})["ok"]
    assert not score_lead({"id": 15, "a": 2}, {"untouched": True}, None, {"id": 15, "a": 1})["ok"]
    assert not score_lead(None, {"category": ["sale"]})["ok"]


def test_summarize_marks_critical_failures() -> None:
    results = {
        "1": {"ok": True, "checks": []},
        "2": {"ok": False, "checks": [{"name": "draft_language", "ok": False, "critical": False}]},
        "3": {"ok": False, "checks": [{"name": "priority", "ok": False, "critical": True}]},
    }
    assert summarize(results) == {
        "total": 3, "passed": 1, "failed_ids": ["2", "3"], "critical_failed_ids": ["3"],
    }  # fmt: skip


def test_clarification_can_be_a_question_or_a_polite_request() -> None:
    assert asks_for_details("Откуда и куда нужно доставить груз?")
    assert asks_for_details("Уточните, пожалуйста, маршрут, вес и объём груза.")
    assert asks_for_details("Please let us know the route and cargo weight.")
    assert asks_for_details("Could you share the pickup address")
    assert not asks_for_details("Спасибо за обращение. Менеджер свяжется с вами.")
    assert not asks_for_details("Thank you, our manager will contact you.")
