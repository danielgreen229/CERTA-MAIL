"""Поддельный OpenAI-совместимый сервер модели для тестов цикла агента.

«Модель» детерминированная: смотрит на историю сообщений и решает, какой инструмент
вызвать дальше. Поведение меняется флагами, чтобы воспроизводить типовые сбои.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

GOOD_DRAFT = "Здравствуйте! Получили ваше обращение. Менеджер уточнит детали и ответит вам."
GOOD_DRAFT_EN = "Hello! We have received your request. Our manager will get back to you."
BAD_DRAFT = "Здравствуйте! Мы работаем с юрлицами, доставка стоит 5000 руб."


@dataclass
class Behaviour:
    stop_after: int | None = None  # перестать вызывать инструменты после N записей (один раз)
    bad_draft_ids: tuple[int, ...] = ()  # сначала отправить черновик с выдуманными фактами
    unknown_tool_once: bool = False
    broken_arguments_once: bool = False
    http_status: int | None = None  # отвечать ошибкой HTTP
    reject_schema: bool = False  # сервер не умеет response_format
    skip_ids: tuple[int, ...] = ()  # «забыть» про эти заявки
    urgent_ids: tuple[int, ...] = ()  # разбор находит последствие: приоритет high
    wrong_priority_once: bool = False  # записать с приоритетом, отличным от разбора
    requests: list[dict[str, Any]] = field(default_factory=list)
    _stopped: bool = False
    _unknown_done: bool = False
    _broken_done: bool = False
    _wrong_done: bool = False


def _tool_call(name: str, arguments: Any, number: int) -> dict[str, Any]:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": f"call_{number}",
                "type": "function",
                "function": {"name": name, "arguments": raw},
            }
        ],
    }


def _decided(messages: list[dict[str, Any]], lead_id: Any) -> tuple[str, str] | None:
    """Значения из сообщения раннера «Решение по заявке …», если оно было."""
    marker = f"Решение по заявке {lead_id!r}:"
    for message in reversed(messages):
        content = str(message.get("content") or "")
        if message.get("role") == "user" and content.startswith(marker):
            category = content.split('category="')[1].split('"')[0]
            priority = content.split('priority="')[1].split('"')[0]
            return category, priority
    return None


def decide(messages: list[dict[str, Any]], behaviour: Behaviour) -> dict[str, Any]:
    """Следующий шаг поддельной модели по истории диалога."""
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    results: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for message in messages:
        for call in message.get("tool_calls") or []:
            try:
                arguments = json.loads(call["function"]["arguments"])
            except json.JSONDecodeError:
                arguments = {}
            calls[call["id"]] = (call["function"]["name"], arguments)
        if message.get("role") == "tool" and message.get("tool_call_id") in calls:
            name, arguments = calls[message["tool_call_id"]]
            results.append((name, arguments, json.loads(message["content"])))
    number = len(calls) + 1

    listing = next((r for name, _a, r in results if name == "list_leads" and r.get("ok")), None)
    if listing is None:
        if behaviour.unknown_tool_once and not behaviour._unknown_done:
            behaviour._unknown_done = True
            return _tool_call("delete_lead", {"id": 1}, number)
        return _tool_call("list_leads", {"status": "new"}, number)

    read = {a["id"] for name, a, r in results if name == "get_lead" and r.get("ok")}
    done = {
        a["id"]
        for name, a, r in results
        if name == "update_lead" and (r.get("ok") or r.get("error", {}).get("code") == "CONFLICT")
    }
    rejected = {
        a["id"]
        for name, a, r in results
        if name == "update_lead" and r.get("error", {}).get("code") == "DRAFT_POLICY"
    }
    if behaviour.stop_after is not None and len(done) >= behaviour.stop_after:
        nudged = any(
            m.get("role") == "user" and "всё ещё в статусе new" in str(m.get("content"))
            for m in messages
        )
        if not nudged and not behaviour._stopped:
            behaviour._stopped = True
            return {"role": "assistant", "content": "Готово."}

    for item in listing["leads"]:
        lead_id = item["id"]
        if lead_id in done or lead_id in behaviour.skip_ids:
            continue
        if lead_id not in read:
            return _tool_call("get_lead", {"id": lead_id}, number)
        text = next(
            r["lead"]["text"] for name, a, r in results if name == "get_lead" and a["id"] == lead_id
        )
        spam = "!!!" in text or "t.me/" in text
        draft: str | None = None if spam else GOOD_DRAFT
        if draft is not None and not any("а" <= ch.lower() <= "я" for ch in text):
            draft = GOOD_DRAFT_EN  # черновик на языке заявки
        if lead_id in behaviour.bad_draft_ids and lead_id not in rejected:
            draft = BAD_DRAFT
        update: Any = {
            "id": lead_id,
            "category": "spam" if spam else "question",
            "priority": "low" if spam else "medium",
            "status": "processed",
            "draft_reply": draft,
        }
        decided = _decided(messages, lead_id)
        if decided is not None:
            update["category"], update["priority"] = decided
            if decided[0] == "spam":
                update["draft_reply"] = None
        if behaviour.wrong_priority_once and not behaviour._wrong_done and not spam:
            behaviour._wrong_done = True
            update["priority"] = "high" if update["priority"] != "high" else "low"
        if behaviour.broken_arguments_once and not behaviour._broken_done:
            behaviour._broken_done = True
            update = '{"id": 1, "category": '
        return _tool_call("update_lead", update, number)
    return {"role": "assistant", "content": "Все заявки обработаны."}


def analysis(messages: list[dict[str, Any]], behaviour: Behaviour) -> dict[str, Any]:
    """Разбор последней прочитанной заявки в формате decision.ANALYSIS_SCHEMA."""
    lead: dict[str, Any] = {}
    for message in messages:
        if message.get("role") == "tool" and '"lead"' in str(message.get("content")):
            lead = json.loads(message["content"])["lead"]
    text = str(lead.get("text", ""))
    spam = "!!!" in text or "t.me/" in text
    urgent = lead.get("id") in behaviour.urgent_ids
    body = {
        "addressed_to_assistant": False,
        "client_message": None if spam else "обращение клиента",
        "kind": "spam" if spam else "question",
        "deadline_quote": None,
        "deadline_date": None,
        "consequence": "wrong_charge" if urgent else "none",
        "consequence_quote": text[:30] if urgent else None,
        "not_urgent": False,
        "uncertain": False,
        "manager_check": None,
        "next_action": "Связаться с клиентом",
    }
    return {"role": "assistant", "content": json.dumps(body, ensure_ascii=False)}


def report(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Структурированный итог по заявкам, которые поддельная модель записала."""
    leads: list[dict[str, Any]] = []
    for message in messages:
        for call in message.get("tool_calls") or []:
            if call["function"]["name"] != "update_lead":
                continue
            try:
                arguments = json.loads(call["function"]["arguments"])
            except json.JSONDecodeError:
                continue
            if any(entry["id"] == arguments.get("id") for entry in leads):
                continue
            leads.append(
                {
                    "id": arguments.get("id"),
                    "category": arguments.get("category"),
                    "priority": arguments.get("priority"),
                    "result": "written",
                    "uncertain": arguments.get("category") == "spam",
                    "manager_check": "проверить" if arguments.get("category") == "spam" else None,
                    "urgency_basis": None,
                    "next_action": None,
                }
            )
    body = json.dumps({"summary": "Сводка поддельной модели.", "leads": leads}, ensure_ascii=False)
    return {"role": "assistant", "content": body}


class FakeLlm:
    """Сервер на localhost. Использование: with FakeLlm(Behaviour(...)) as fake: fake.url"""

    def __init__(self, behaviour: Behaviour | None = None) -> None:
        self.behaviour = behaviour or Behaviour()
        behaviour_ref = self.behaviour

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length))
                behaviour_ref.requests.append(payload)
                if behaviour_ref.http_status:
                    self._send(behaviour_ref.http_status, {"error": {"message": "fake failure"}})
                    return
                if "response_format" in payload:
                    if behaviour_ref.reject_schema:
                        self._send(400, {"error": {"message": "response_format unsupported"}})
                        return
                    name = payload["response_format"]["json_schema"]["name"]
                    if name == "lead_analysis":
                        message = analysis(payload["messages"], behaviour_ref)
                    else:
                        message = report(payload["messages"])
                else:
                    message = decide(payload["messages"], behaviour_ref)
                self._send(
                    200,
                    {
                        "model": "fake-model",
                        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 10},
                    },
                )

            def _send(self, status: int, body: dict[str, Any]) -> None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args: Any) -> None:  # тишина в выводе тестов
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def __enter__(self) -> FakeLlm:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
