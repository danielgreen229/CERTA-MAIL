"""Выгрузка списка писем (с текущими фильтрами) в JSON, Excel, Word и PDF.

Excel и Word собираются как минимальные документы Office Open XML без сторонних
библиотек; PDF — через fpdf2 со шрифтом TrueType с кириллицей (DejaVu Sans в образе
Docker, Arial на Windows; свой путь — переменная ``LEADS_PDF_FONT``).
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from lead_assistant.web.leads import LeadView

CATEGORY = {"sale": "Продажа", "complaint": "Жалоба", "question": "Вопрос", "spam": "Спам"}
PRIORITY = {"high": "Высокий", "medium": "Средний", "low": "Низкий"}

COLUMNS: tuple[tuple[str, str, int], ...] = (
    # ключ, заголовок, ширина колонки Excel (в символах)
    ("id", "№", 6),
    ("date", "Дата", 11),
    ("channel", "Канал", 10),
    ("inbox", "Ящик", 22),
    ("name", "Отправитель", 22),
    ("contact", "Контакт", 26),
    ("category", "Категория", 11),
    ("priority", "Срочность", 10),
    ("state", "Состояние", 18),
    ("assignee", "Ответственный", 18),
    ("due_at", "Срок реакции", 17),
    ("text", "Текст обращения", 60),
    ("draft_reply", "Черновик ответа", 60),
)

FORMATS = {
    "json": ("application/json; charset=utf-8", "json"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "pdf": ("application/pdf", "pdf"),
}

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
)

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class ExportError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def rows(views: Sequence[LeadView]) -> list[dict[str, str]]:
    out = []
    for view in views:
        lead = view.lead
        summary = view.summary()
        due = str(summary.get("due_at") or "")
        out.append(
            {
                "id": str(lead.get("id")),
                "date": str(lead.get("date") or ""),
                "channel": str(lead.get("channel") or ""),
                "inbox": str(lead.get("inbox") or ""),
                "name": str(lead.get("name") or ""),
                "contact": str(lead.get("contact") or ""),
                "category": CATEGORY.get(str(lead.get("category")), ""),
                "priority": PRIORITY.get(str(lead.get("priority")), ""),
                "state": str(summary.get("state_title") or ""),
                "assignee": str(summary.get("assignee") or ""),
                "due_at": due[:16].replace("T", " "),
                "text": str(lead.get("text") or ""),
                "draft_reply": str(lead.get("draft_reply") or ""),
            }
        )
    return out


def render(fmt: str, views: Sequence[LeadView]) -> tuple[bytes, str, str]:
    if fmt not in FORMATS:
        raise ExportError("INVALID_ARGUMENT", "Формат выгрузки: json, xlsx, docx или pdf")
    media_type, ext = FORMATS[fmt]
    data = rows(views)
    if fmt == "json":
        payload = [{**view.lead, "state": view.state, **_extra(view)} for view in views]
        content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    elif fmt == "xlsx":
        content = to_xlsx(data)
    elif fmt == "docx":
        content = to_docx(data)
    else:
        content = to_pdf(data)
    return content, media_type, ext


def _extra(view: LeadView) -> dict[str, Any]:
    summary = view.summary()
    return {
        "assignee": summary.get("assignee"),
        "due_at": summary.get("due_at"),
        "review_reasons": [reason.get("text") for reason in summary.get("review_reasons") or []],
    }


def _xml(text: str) -> str:
    return escape(_CONTROL.sub("", text))


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in files.items():
            archive.writestr(name, body.encode("utf-8"))
    return buffer.getvalue()


def _column(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def to_xlsx(data: list[dict[str, str]]) -> bytes:
    def cell(ref: str, value: str, style: int = 0) -> str:
        return (
            f'<c r="{ref}" t="inlineStr" s="{style}"><is><t xml:space="preserve">'
            f"{_xml(value)}</t></is></c>"
        )

    lines = [
        '<row r="1">'
        + "".join(cell(f"{_column(i)}1", title, 1) for i, (_, title, _) in enumerate(COLUMNS))
        + "</row>"
    ]
    for number, row in enumerate(data, start=2):
        lines.append(
            f'<row r="{number}">'
            + "".join(
                cell(f"{_column(i)}{number}", row[key], 2) for i, (key, _, _) in enumerate(COLUMNS)
            )
            + "</row>"
        )
    cols = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{width}" customWidth="1"/>'
        for i, (_, _, width) in enumerate(COLUMNS)
    )
    last = f"{_column(len(COLUMNS) - 1)}{max(len(data) + 1, 1)}"
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<cols>{cols}</cols><sheetData>{''.join(lines)}</sheetData>"
        f'<autoFilter ref="A1:{last}"/></worksheet>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="3"><xf/><xf fontId="1" applyFont="1"/>'
        '<xf applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs>'
        "</styleSheet>"
    )
    return _zip(
        {
            "[Content_Types].xml": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" '
                'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/xl/workbook.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                '<Override PartName="/xl/styles.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                "</Types>"
            ),
            "_rels/.rels": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
                '2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
            ),
            "xl/workbook.xml": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="Почта" sheetId="1" r:id="rId1"/></sheets>'
                '<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" '
                f"hidden=\"1\">'Почта'!$A$1:${last.rstrip('0123456789')}${max(len(data) + 1, 1)}"
                "</definedName></definedNames></workbook>"
            ),
            "xl/_rels/workbook.xml.rels": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
                '2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/'
                '2006/relationships/styles" Target="styles.xml"/></Relationships>'
            ),
            "xl/worksheets/sheet1.xml": sheet,
            "xl/styles.xml": styles,
        }
    )


def to_docx(data: list[dict[str, str]]) -> bytes:
    def run(
        text: str, bold: bool = False, size: int | None = None, color: str | None = None
    ) -> str:
        props = ""
        if bold or size or color:
            props = (
                "<w:rPr>"
                + ("<w:b/>" if bold else "")
                + (f'<w:color w:val="{color}"/>' if color else "")
                + (f'<w:sz w:val="{size}"/>' if size else "")
                + "</w:rPr>"
            )
        parts = _xml(text).split("\n")
        body = "<w:br/>".join(f'<w:t xml:space="preserve">{part}</w:t>' for part in parts)
        return f"<w:r>{props}{body}</w:r>"

    def para(*runs: str, spacing: int = 60) -> str:
        return f'<w:p><w:pPr><w:spacing w:after="{spacing}"/></w:pPr>{"".join(runs)}</w:p>'

    stamp = datetime.now(UTC).strftime("%d.%m.%Y %H:%M UTC")
    blocks = [
        para(run("Почта — выгрузка", bold=True, size=32), spacing=80),
        para(run(f"Сформировано {stamp} · писем: {len(data)}", color="666666"), spacing=200),
    ]
    for row in data:
        head = f"№ {row['id']} · {row['date']} · {row['channel']}"
        meta = " · ".join(
            value
            for value in (row["category"], row["priority"], row["state"], row["assignee"])
            if value
        )
        sender = " · ".join(value for value in (row["name"], row["contact"], row["inbox"]) if value)
        blocks.append(para(run(head, bold=True, size=24), spacing=20))
        blocks.append(para(run(sender, color="555555"), spacing=20))
        if meta:
            blocks.append(para(run(meta, color="1F5FBF"), spacing=60))
        blocks.append(para(run(row["text"])))
        if row["draft_reply"]:
            blocks.append(para(run("Черновик ответа: ", bold=True), run(row["draft_reply"])))
        blocks.append(
            '<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="4" w:space="1" '
            'w:color="DDDDDD"/></w:pBdr><w:spacing w:after="160"/></w:pPr></w:p>'
        )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(blocks)}"
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="850" w:bottom="1134" w:left="1134"/></w:sectPr>'
        "</w:body></w:document>"
    )
    return _zip(
        {
            "[Content_Types].xml": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" '
                'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                "</Types>"
            ),
            "_rels/.rels": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
                '2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
            ),
            "word/document.xml": document,
        }
    )


def pdf_font() -> Path:
    configured = os.environ.get("LEADS_PDF_FONT")
    for candidate in ([configured] if configured else []) + list(FONT_CANDIDATES):
        path = Path(candidate)
        if path.is_file():
            return path
    raise ExportError(
        "PDF_FONT",
        "Нет шрифта с кириллицей для PDF: укажите путь к .ttf в LEADS_PDF_FONT",
    )


def to_pdf(data: list[dict[str, str]]) -> bytes:
    from fpdf import FPDF  # импорт здесь: остальные форматы не зависят от fpdf2

    font = pdf_font()
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font("Body", "", str(font))
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin

    def write(text: str, size: float, color: tuple[int, int, int] = (28, 36, 48)) -> None:
        pdf.set_font("Body", size=size)
        pdf.set_text_color(*color)
        pdf.multi_cell(width, size * 0.5, _CONTROL.sub("", text), new_x="LMARGIN", new_y="NEXT")

    stamp = datetime.now(UTC).strftime("%d.%m.%Y %H:%M UTC")
    write("Почта — выгрузка", 16)
    write(f"Сформировано {stamp} · писем: {len(data)}", 9, (100, 104, 120))
    pdf.ln(3)
    for row in data:
        write(f"№ {row['id']} · {row['date']} · {row['channel']}", 12)
        sender = " · ".join(v for v in (row["name"], row["contact"], row["inbox"]) if v)
        write(sender, 9, (90, 96, 110))
        meta = " · ".join(
            v for v in (row["category"], row["priority"], row["state"], row["assignee"]) if v
        )
        if meta:
            write(meta, 9, (31, 95, 191))
        write(row["text"], 10)
        if row["draft_reply"]:
            write("Черновик ответа: " + row["draft_reply"], 10, (60, 70, 85))
        pdf.ln(1)
        pdf.set_draw_color(221, 226, 234)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(3)
    return bytes(pdf.output())
