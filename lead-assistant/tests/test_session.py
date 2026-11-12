"""Сессия вне раннера: ручные вызовы инструментов через stdio и сверка по трейсу сервера."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from lead_assistant import evals, session
from lead_assistant.storage import sha256_hex

DRAFT = "Здравствуйте! Уточните, пожалуйста, детали."


def mcp_call(env: dict[str, str], tool: str, **arguments: Any) -> tuple[int, dict[str, Any]]:
    """Отдельный процесс на каждый вызов — как при работе из командной строки."""
    import os

    completed = subprocess.run(
        [sys.executable, "-m", "lead_assistant.mcp_call", tool, json.dumps(arguments)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **env},
        timeout=120,
        check=False,
    )
    text = completed.stdout
    return completed.returncode, json.loads(text[text.index("{") :])


def test_external_session_is_reconciled_from_server_trace(leads_file: Path) -> None:
    meta = session.begin(leads_file, leads_file.parent / "runs", "2026-11-11")
    env = meta["env"]
    run_dir = Path(meta["run_dir"])

    code, listing = mcp_call(env, "list_leads", status="new")
    assert code == 0 and listing["count"] == 14
    entries = []
    for item in listing["leads"][:3]:
        mcp_call(env, "get_lead", id=item["id"])
        spam = item["id"] == 3
        code, payload = mcp_call(
            env,
            "update_lead",
            id=item["id"],
            category="spam" if spam else "question",
            priority="low" if spam else "medium",
            status="processed",
            draft_reply=None if spam else DRAFT,
        )
        assert code == 0 and payload["result"] == "updated"
        entries.append(
            {
                "id": item["id"],
                "category": "spam" if spam else "question",
                "priority": "low" if spam else "medium",
                "result": "written",
                "uncertain": spam,
                "manager_check": "проверить" if spam else None,
            }
        )
    code, rejected = mcp_call(
        env,
        "update_lead",
        id=4,
        category="vip",
        priority="high",
        status="processed",
        draft_reply="x",
    )
    assert code == 1 and rejected["error"]["code"] == "INVALID_ARGUMENT"

    report = "Сводка.\n```json\n" + json.dumps({"leads": entries}, ensure_ascii=False) + "\n```"
    run = session.end(run_dir, report, "claude-opus-5-5")
    rec = run["reconciliation"]

    assert run["runtime"]["backend"] == "external-session"
    assert rec["counts"] == {"found": 14, "written": 3, "already_processed": 0, "failed": 11}
    assert rec["written_ids"] == [1, 2, 3] and rec["counts_consistent"]
    assert {"id": 4, "reason": "INVALID_ARGUMENT"} in rec["failed"]
    assert run["status"] == "incomplete"
    assert run["metrics"]["tool_calls"]["by_tool"] == {
        "list_leads": 1,
        "get_lead": 3,
        "update_lead": 4,
    }
    assert run["metrics"]["cost"]["status"] == "unavailable"  # телеметрии модели нет
    assert run["leads_file"]["sha256_after"] == sha256_hex(leads_file.read_bytes())
    assert (run_dir / "summary.md").exists() and (run_dir / "model_report.md").exists()
    assert not (run_dir / session.BEFORE_COPY).exists()  # копия данных удалена


def test_fixture_and_score_commands(tmp_path: Path) -> None:
    fixture = tmp_path / "eval dir" / "leads.json"
    assert evals.main(["fixture", "--out", str(fixture)]) == 0
    meta = session.begin(fixture, tmp_path / "runs", "2026-11-10")
    run = session.end(Path(meta["run_dir"]), "", None)
    assert run["reconciliation"]["counts"]["found"] == 17

    code = evals.main(
        ["score", "--fixture", str(fixture), "--run", str(Path(run["run_dir"]) / "run.json")]
    )
    assert code == 1  # ничего не обработано — набор не пройден
    report = json.loads((Path(run["run_dir"]) / "eval_report.json").read_text("utf-8"))
    assert report["summary"]["total"] == 18 and report["results"]["199"]["ok"]
    assert report["backend"] == "external-session"


def test_session_end_can_be_repeated_when_report_is_unreadable(leads_file: Path) -> None:
    meta = session.begin(leads_file, leads_file.parent / "runs", "2026-11-11")
    run_dir = Path(meta["run_dir"])

    empty = leads_file.parent / "empty.md"
    empty.write_text("", encoding="utf-8")
    assert session.main(["end", str(run_dir), "--report", str(empty)]) == 2
    assert (run_dir / session.BEFORE_COPY).exists() and not (run_dir / "run.json").exists()

    broken = session.end(run_dir, "Итог без блока json", None)
    assert broken["before_copy_kept"] is True
    assert "REPORT_MISSING" in broken["reconciliation"]["warnings"]
    assert (run_dir / session.BEFORE_COPY).exists()  # сверку можно повторить

    fixed = session.end(run_dir, 'Итог.\n```json\n{"leads": []}\n```', None)
    assert fixed["before_copy_kept"] is False
    assert not (run_dir / session.BEFORE_COPY).exists()
