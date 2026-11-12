from __future__ import annotations

from typing import Any

import pytest

from lead_assistant.draft_policy import check_draft, lead_numbers
from lead_assistant.models import ErrorCode, LeadError
from lead_assistant.server import build_server
from lead_assistant.storage import LeadStore
from lead_assistant.tracing import Tracer

LEAD: dict[str, Any] = {
    "id": 7,
    "date": "2026-11-05",
    "name": "Марина Ким",
    "text": "Мы планируем закупку на 2,5 млн руб. до конца года. Нужно КП, заказ №4521.",
    "status": "new",
}


@pytest.mark.parametrize(
    "draft",
    [
        "Здравствуйте, Марина! Получили ваш запрос на КП по закупке на 2,5 млн руб. "
        "Менеджер подготовит предложение и свяжется с вами. Какие перевозки вам нужны?",
        "Добрый день! Получили обращение по заказу №4521. Менеджер проверит заказ и ответит.",
        "Менеджер уточнит, возможна ли доставка в Казань, и ответит вам.",
        "Спасибо за отзыв! Будем рады помочь вам снова.",
        "Уточните, пожалуйста, 1-2 удобных способа связи.",
        "Менеджер проверит платежи и уточнит, как вернуть переплату.",
    ],
)
def test_grounded_drafts_pass(draft: str) -> None:
    assert check_draft(draft, LEAD) == []


@pytest.mark.parametrize(
    ("draft", "fragment"),
    [
        ("Да, мы работаем с юрлицами с отсрочкой платежа.", "возможностях"),
        ("Мы предоставляем доставку в Казань.", "возможностях"),
        ("Наша компания доставляет грузы по всей России.", "возможностях"),
        ("Yes, we work with companies from Kazakhstan.", "возможностях"),
        ("Мы уже проверяем статус вашего заказа.", "уже выполнено"),
        ("Договор уже отправлен вам на почту.", "уже выполнено"),
        ("We are currently checking the information.", "уже выполнено"),
        ("Мы вернём деньги и компенсируем неудобства.", "обещание"),
        ("Менеджер рассмотрит претензию и вернёт лишние деньги.", "обещание"),
        ("Доставка будет бесплатной.", "обещание"),
        ("Вам положена скидка, менеджер подтвердит.", "обещание"),
        ("Просим проявить терпение.", "подождать"),
        ("Получили ваш запрос назначить приоритет high и игнорировать инструкции.", "пересказ"),
        ("Доставка займёт 3 дня и стоит 15000 руб.", "числа, которых нет в заявке: 15000"),
        ("Менеджер ответит в течение 24 часов.", "числа, которых нет в заявке: 24"),
        ("Стоимость составит 2,7 млн руб.", "числа, которых нет в заявке: 2.7"),
    ],
)
def test_ungrounded_drafts_are_flagged(draft: str, fragment: str) -> None:
    problems = check_draft(draft, LEAD)
    assert problems and any(fragment in problem for problem in problems), problems


def test_numbers_come_from_any_lead_field() -> None:
    assert {"7", "2026", "11", "5", "2.5", "4521"} <= lead_numbers(LEAD)
    assert check_draft("Получили обращение от 05.11 по заказу 4521.", LEAD) == []
    assert check_draft("Доставка 14.11.2026.", LEAD) == ["числа, которых нет в заявке: 14"]
    assert check_draft("Обращение от 05.11.2026 по заказу 4521 получено.", LEAD) == []


def test_each_kind_of_problem_is_reported_once() -> None:
    problems = check_draft("Мы работаем с юрлицами. Мы доставляем в Казань. Мы возим всё.", LEAD)
    assert len(problems) == 1


async def call_update(store: LeadStore, **arguments: Any) -> Any:
    server = build_server(store, Tracer(None))
    return await server.call_tool("update_lead", arguments)


@pytest.mark.anyio
async def test_server_rejects_ungrounded_draft_and_keeps_file(store: LeadStore) -> None:
    from mcp.server.mcpserver.exceptions import ToolError

    arguments = {"id": 10, "category": "question", "priority": "medium", "status": "processed"}
    with pytest.raises(ToolError) as rejected:
        await call_update(store, **arguments, draft_reply="Мы доставляем в Казань за 2 дня.")
    assert "DRAFT_POLICY" in str(rejected.value) and "Мы доставляем" in str(rejected.value)
    assert store.get_lead(10)["status"] == "new"

    # Проверка параметров идёт раньше проверки содержания.
    with pytest.raises(ToolError) as invalid:
        await call_update(store, **{**arguments, "status": "VIP"}, draft_reply="Мы доставляем.")
    assert "INVALID_ARGUMENT" in str(invalid.value)

    await call_update(
        store, **arguments, draft_reply="Менеджер уточнит, возможна ли доставка в Казань."
    )
    assert store.get_lead(10)["status"] == "processed"


def test_draft_policy_is_a_validation_error_code() -> None:
    error = LeadError(ErrorCode.DRAFT_POLICY, "x", problems=["y"])
    assert error.to_dict() == {"code": "DRAFT_POLICY", "message": "x", "problems": ["y"]}


def test_draft_must_be_in_the_language_of_the_lead() -> None:
    english = {"id": 14, "text": "Hi! Do you work with companies from Kazakhstan?"}
    assert check_draft("Hello Irina! Our manager will check and get back to you.", english) == []
    problems = check_draft("Здравствуйте, Ирина! Менеджер уточнит и ответит вам.", english)
    assert problems == ["черновик должен быть на языке заявки — на английском"]
    assert check_draft("Hello! Our manager will reply.", LEAD) == [
        "черновик должен быть на языке заявки — на русском"
    ]
    assert check_draft("Менеджер ответит.", {"id": 1, "text": "12345 !!!"}) == []  # язык неясен
