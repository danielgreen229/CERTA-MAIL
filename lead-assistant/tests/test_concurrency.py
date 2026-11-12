"""Параллельные записи независимыми процессами (отдельные интерпретаторы)."""

from __future__ import annotations

from pathlib import Path

from lead_assistant.storage import parse_leads
from tests.helpers import ORIGINAL, finish_worker, start_worker


def by_id(path: Path) -> dict[int, dict[str, object]]:
    return {lead["id"]: lead for lead in parse_leads(path.read_bytes())}


def test_parallel_updates_of_different_leads_are_not_lost(leads_file: Path, tmp_path: Path) -> None:
    go = tmp_path / "go"
    ids = list(range(1, 13))
    workers = [
        start_worker(
            leads_file, "update", str(i), "question", "medium", f"Ответ {i}", "--go", str(go)
        )
        for i in ids
    ]
    go.write_text("go", encoding="utf-8")  # все процессы стартуют одновременно
    outcomes = [finish_worker(worker) for worker in workers]

    assert [payload.get("result") for _, payload in outcomes] == ["updated"] * len(ids)
    assert len({payload["pid"] for _, payload in outcomes}) == len(ids)  # процессы разные

    after = by_id(leads_file)
    original = {lead["id"]: lead for lead in parse_leads(ORIGINAL.read_bytes())}
    assert list(after) == list(original)  # порядок и состав сохранены
    for i in ids:
        assert after[i]["status"] == "processed"
        assert after[i]["draft_reply"] == f"Ответ {i}"  # ни одно обновление не потеряно
    for untouched in (13, 14, 15):
        assert after[untouched] == original[untouched]


def test_parallel_updates_of_same_lead_have_single_winner(leads_file: Path, tmp_path: Path) -> None:
    go = tmp_path / "go"
    workers = [
        start_worker(leads_file, "update", "7", "sale", "high", f"Вариант {n}", "--go", str(go))
        for n in range(8)
    ]
    go.write_text("go", encoding="utf-8")
    outcomes = [payload for _, payload in (finish_worker(worker) for worker in workers)]

    winners = [n for n, payload in enumerate(outcomes) if payload.get("result") == "updated"]
    conflicts = [payload for payload in outcomes if payload.get("code") == "CONFLICT"]
    assert len(winners) == 1
    assert len(conflicts) == 7
    assert by_id(leads_file)[7]["draft_reply"] == f"Вариант {winners[0]}"


def test_parallel_repeats_with_same_values_write_once(leads_file: Path, tmp_path: Path) -> None:
    go = tmp_path / "go"
    workers = [
        start_worker(leads_file, "update", "3", "spam", "low", "null", "--go", str(go))
        for _ in range(6)
    ]
    go.write_text("go", encoding="utf-8")
    results = sorted(payload["result"] for _, payload in (finish_worker(w) for w in workers))
    assert results == ["unchanged"] * 5 + ["updated"]
