"""Демонстрационные письма: разбираются коннектором и покрывают все папки панели."""

from __future__ import annotations

from pathlib import Path

from lead_assistant.web import connectors, demo_mail


def test_twenty_distinct_messages_cover_every_category_and_priority() -> None:
    built = demo_mail.build_all()
    assert len(built) == 20
    assert len({message["Message-ID"] for _, message in built}) == 20
    expected = [demo.expect for demo, _ in built]
    assert {e["category"] for e in expected} == {"sale", "complaint", "question", "spam"}
    assert {e["priority"] for e in expected} == {"high", "medium", "low"}


def test_every_message_is_parsed_into_a_lead_with_text_and_sender() -> None:
    for demo, message in demo_mail.build_all():
        item = connectors.normalize_email(message.as_bytes())
        lead = item["lead"]
        assert item["external_id"] == f"<{demo.key}@demo.lead-assistant.example>"
        assert lead["channel"] == "email" and "@" in lead["contact"]
        assert lead["text"].strip(), demo.key
        assert "<" not in lead["text"], f"{demo.key}: HTML не превращён в текст"
    by_key = {
        demo.key: connectors.normalize_email(m.as_bytes())["lead"]
        for demo, m in demo_mail.build_all()
    }
    assert "Груз повреждён — накладная 55120" in by_key["complaint-damage"]["text"]
    assert "линия стоит" in by_key["complaint-downtime-html"]["text"]
    assert "два дня позже" in by_key["complaint-cp1251"]["text"], "cp1251 раскодирован"
    assert by_key["subject-only"]["text"] == "Нужна газель по Москве на послезавтра, 1.5 т"
    assert "48 300" in by_key["complaint-double-charge"]["text"], "вложение не мешает телу"


def test_dry_run_writes_eml_files(tmp_path: Path) -> None:
    assert demo_mail.main(["--dry-run", str(tmp_path)]) == 0
    files = sorted(tmp_path.glob("*.eml"))
    assert len(files) == 20 and files[0].name.startswith("01-")
