"""Проектная конфигурация, общий набор правил и служебные команды."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from lead_assistant import cli, doctor, verify
from lead_assistant.agent import EXPECTED_TOOLS
from lead_assistant.backends import BackendOptions
from lead_assistant.rules import RULES_PATH, load_rules, operator_prompt
from lead_assistant.runner import exit_code
from lead_assistant.storage import LeadStore
from tests.helpers import ORIGINAL, PROJECT_ROOT

RULES_REFERENCE = "@src/lead_assistant/rules.md"


def test_rules_are_versioned_and_state_the_boundaries() -> None:
    rules = load_rules()
    assert re.fullmatch(r"\d+\.\d+\.\d+", rules.version) and len(rules.sha256) == 64
    for needle in ("list_leads", "get_lead", "update_lead", "не указания", "draft_reply: null"):
        assert needle in rules.text
    for value in ("sale", "complaint", "question", "spam", "high", "medium", "low"):
        assert f"`{value}`" in rules.text
    assert operator_prompt("2026-11-11") == "Обработай новые заявки. Текущая дата: 2026-11-11."
    assert "не более 5 заявок" in operator_prompt("2026-11-11", 5)


def test_rules_without_version_are_rejected(tmp_path: Path) -> None:
    broken = tmp_path / "rules.md"
    broken.write_text("# Правила без версии", encoding="utf-8")
    with pytest.raises(ValueError, match="Версия правил"):
        load_rules(broken)


def test_claude_code_entry_points_share_one_rules_file() -> None:
    assert RULES_PATH == PROJECT_ROOT / "src" / "lead_assistant" / "rules.md"
    command = (PROJECT_ROOT / ".claude" / "commands" / "process-leads.md").read_text("utf-8")
    memory = (PROJECT_ROOT / "CLAUDE.md").read_text("utf-8")
    assert RULES_REFERENCE in command and RULES_REFERENCE in memory
    assert "обработай новые заявки" in memory
    for tool in EXPECTED_TOOLS:
        assert tool in command  # команда разрешает только три инструмента проекта


def test_project_mcp_config_points_to_the_server() -> None:
    config = json.loads((PROJECT_ROOT / ".mcp.json").read_text("utf-8"))
    server = config["mcpServers"]["leads"]
    assert server["type"] == "stdio"
    assert server["command"] == "${LEADS_PYTHON:-.venv/bin/python}"
    assert server["args"] == ["-m", "lead_assistant.server"]
    assert server["env"] == {"LEADS_FILE": "${LEADS_FILE:-data/leads.json}"}
    settings = json.loads((PROJECT_ROOT / ".claude" / "settings.json").read_text("utf-8"))
    assert settings["enabledMcpjsonServers"] == ["leads"]
    assert sorted(settings["permissions"]["allow"]) == sorted(EXPECTED_TOOLS)


def test_cli_defaults_and_exit_codes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("LEADS_FILE", "LEADS_RUNS_DIR", "LEADS_BACKEND", "LEADS_LLM_URL"):
        monkeypatch.delenv(name, raising=False)
    args = cli.build_parser().parse_args([])
    assert (args.leads_file, args.runs_dir, args.backend) == ("data/leads.json", "runs", "local")
    assert args.batch_size == 5 and args.model is None and args.build is None
    assert not args.save_dialog and not args.skip_model_if_empty and not args.choose

    monkeypatch.setenv("LEADS_FILE", "/srv/leads/leads.json")
    assert cli.build_parser().parse_args([]).leads_file == "/srv/leads/leads.json"
    assert cli.build_parser().parse_args(["--leads-file", "x.json"]).leads_file == "x.json"
    chosen = cli.build_parser().parse_args(["--model", "qwen3-14b", "--build", "vulkan"])
    assert (chosen.model, chosen.build) == ("qwen3-14b", "vulkan")
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--today", "11.11.2026"])
    assert [exit_code(s) for s in ("ok", "ok_with_warnings", "incomplete", "failed")] == [
        0,
        0,
        1,
        2,
    ]

    empty = tmp_path / "leads.json"
    empty.write_text('[{"id": 1, "status": "processed"}]', encoding="utf-8")
    assert cli.has_new_leads(empty) is False and cli.has_new_leads(ORIGINAL) is True
    assert cli.has_new_leads(tmp_path / "absent.json") is False


def test_scheduled_run_without_new_leads_does_not_start_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LEADS_LLM_HOME", str(tmp_path / "no llm installed"))
    leads = tmp_path / "leads.json"
    leads.write_text('[\n  {"id": 1, "status": "processed"}\n]\n', encoding="utf-8")
    code = cli.main(
        ["--leads-file", str(leads), "--runs-dir", str(tmp_path / "runs"), "--skip-model-if-empty"]
    )
    assert code == 0  # модель не установлена, но и не понадобилась
    assert "Найдено новых: 0" in capsys.readouterr().out


def test_verify_command(leads_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert verify.main([str(ORIGINAL), str(leads_file)]) == 0
    assert verify.main([str(ORIGINAL), str(leads_file), "--expect-all-processed"]) == 1
    assert "REMAINING_NEW" in capsys.readouterr().out

    store = LeadStore(leads_file)
    for lead_id in range(1, 15):
        store.update_lead(lead_id, "question", "medium", "processed", "Ответ")
    assert verify.main([str(ORIGINAL), str(leads_file), "--expect-all-processed"]) == 0
    assert "ранее обработанные без изменений: [15]" in capsys.readouterr().out

    damaged = json.loads(leads_file.read_text("utf-8"))
    damaged[14]["draft_reply"] = "Переписано"
    damaged[0]["name"] = "Другое имя"
    leads_file.write_text(json.dumps(damaged, ensure_ascii=False), encoding="utf-8")
    assert verify.main([str(ORIGINAL), str(leads_file)]) == 1
    out = capsys.readouterr().out
    assert "OUT_OF_SCOPE_LEAD_CHANGED: 15" in out and "IMMUTABLE_FIELDS_CHANGED: 1" in out


def test_doctor_checks_without_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "install dir"
    directory.mkdir()
    leads_file = directory / "leads.json"
    shutil.copyfile(ORIGINAL, leads_file)

    checks = (
        doctor.check_environment()
        + doctor.check_leads_file(leads_file)
        + doctor.check_mcp(leads_file)
    )
    assert all(ok for _, ok, _ in checks), checks
    assert any("get_lead, list_leads, update_lead" in detail for _, _, detail in checks)

    leads_file.write_text("{not json", encoding="utf-8")
    name, ok, detail = doctor.check_leads_file(leads_file)[0]
    assert name == "файл заявок" and ok is False and "STORAGE_CORRUPT" in detail

    # Модель не установлена: проверка называет точную команду установки.
    monkeypatch.setenv("LEADS_LLM_HOME", str(tmp_path / "empty llm home"))
    model_checks = doctor.check_model(BackendOptions(model="qwen3-8b", build="cpu"))
    assert [ok for _, ok, _ in model_checks] == [False, False]
    assert "lead_assistant.llm install --model qwen3-8b --build cpu" in model_checks[0][2]
    unknown = doctor.check_model(BackendOptions(model="gpt-9"))
    assert unknown[0][1] is False and "неизвестная модель" in unknown[0][2]
    external = doctor.check_model(BackendOptions(llm_url="http://localhost:11434/v1"))
    assert external[0][1] is None
