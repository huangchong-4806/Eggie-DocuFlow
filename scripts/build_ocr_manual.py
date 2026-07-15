#!/usr/bin/env python3
import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = PROJECT_ROOT / "docs" / "OCR使用说明.md"
OUTPUT_FILE = PROJECT_ROOT / "docs" / "OCR使用说明.pdf"
FONT_NAME = "EggieManualSongti"
FONT_BOLD_NAME = "EggieManualSongtiBold"
FONT_FILE = Path("/System/Library/Fonts/Supplemental/Songti.ttc")


def register_fonts():
    if not FONT_FILE.is_file():
        raise FileNotFoundError(f"缺少说明书中文字体：{FONT_FILE}")
    pdfmetrics.registerFont(
        TTFont(FONT_NAME, str(FONT_FILE), subfontIndex=6)
    )
    pdfmetrics.registerFont(
        TTFont(FONT_BOLD_NAME, str(FONT_FILE), subfontIndex=1)
    )
    pdfmetrics.registerFontFamily(
        FONT_NAME,
        normal=FONT_NAME,
        bold=FONT_BOLD_NAME,
    )


def inline_markup(value):
    escaped = html.escape(value.strip())
    escaped = re.sub(
        r"`([^`]+)`",
        rf'<font name="{FONT_NAME}" backColor="#EAF2F8">\1</font>',
        escaped,
    )
    escaped = re.sub(
        r"(https://[^\s<]+)",
        r'<link href="\1" color="#146C94"><u>\1</u></link>',
        escaped,
    )
    return escaped


def build_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleCN",
            parent=base["Title"],
            fontName=FONT_BOLD_NAME,
            fontSize=23,
            leading=31,
            textColor=colors.HexColor("#17365D"),
            alignment=TA_CENTER,
            spaceAfter=10 * mm,
            wordWrap="CJK",
        ),
        "h2": ParagraphStyle(
            "Heading2CN",
            parent=base["Heading2"],
            fontName=FONT_BOLD_NAME,
            fontSize=15,
            leading=22,
            textColor=colors.HexColor("#17365D"),
            spaceBefore=6 * mm,
            spaceAfter=3 * mm,
            keepWithNext=True,
            wordWrap="CJK",
        ),
        "h3": ParagraphStyle(
            "Heading3CN",
            parent=base["Heading3"],
            fontName=FONT_BOLD_NAME,
            fontSize=12,
            leading=18,
            textColor=colors.HexColor("#146C94"),
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
            keepWithNext=True,
            wordWrap="CJK",
        ),
        "body": ParagraphStyle(
            "BodyCN",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=9.4,
            leading=15.5,
            textColor=colors.HexColor("#25364A"),
            alignment=TA_LEFT,
            spaceAfter=2.2 * mm,
            wordWrap="CJK",
        ),
        "list": ParagraphStyle(
            "ListCN",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=9.2,
            leading=15,
            leftIndent=6 * mm,
            firstLineIndent=-4.5 * mm,
            spaceAfter=1.4 * mm,
            textColor=colors.HexColor("#25364A"),
            wordWrap="CJK",
        ),
        "meta": ParagraphStyle(
            "MetaCN",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=9.5,
            leading=17,
            textColor=colors.HexColor("#4C6075"),
            alignment=TA_CENTER,
            wordWrap="CJK",
        ),
        "callout": ParagraphStyle(
            "CalloutCN",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=10,
            leading=17,
            textColor=colors.HexColor("#17365D"),
            wordWrap="CJK",
        ),
    }


def page_decorations(canvas, document):
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(colors.HexColor("#D9E2EC"))
    canvas.setLineWidth(0.6)
    canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
    canvas.setFont(FONT_NAME, 7.5)
    canvas.setFillColor(colors.HexColor("#6B7C8F"))
    canvas.drawString(18 * mm, 9 * mm, "Eggie DocuFlow OCR 使用说明")
    canvas.drawRightString(width - 18 * mm, 9 * mm, f"第 {document.page} 页")
    canvas.restoreState()


def parse_markdown(lines, styles):
    story = []
    paragraph_lines = []

    def flush_paragraph():
        if not paragraph_lines:
            return
        value = " ".join(line.strip() for line in paragraph_lines).strip()
        if value:
            story.append(Paragraph(inline_markup(value), styles["body"]))
        paragraph_lines.clear()

    title_seen = False
    meta_lines = []
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            continue
        if stripped.startswith("# "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(stripped[2:]), styles["title"]))
            title_seen = True
            continue
        if title_seen and len(meta_lines) < 3 and (
            stripped.startswith("版本：")
            or stripped.startswith("更新日期：")
            or stripped.startswith("适用软件：")
        ):
            meta_lines.append(stripped.rstrip("  "))
            if len(meta_lines) == 3:
                story.append(
                    Paragraph("<br/>".join(map(inline_markup, meta_lines)), styles["meta"])
                )
                story.append(Spacer(1, 6 * mm))
                callout = Paragraph(
                    "核心提醒：文本页只在本机读取；仅扫描页会在您确认后发送给所选 OCR 平台。",
                    styles["callout"],
                )
                box = Table([[callout]], colWidths=[165 * mm])
                box.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF4F8")),
                            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#7BB6CE")),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                            ("TOPPADDING", (0, 0), (-1, -1), 8),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                        ]
                    )
                )
                story.append(box)
                story.append(Spacer(1, 5 * mm))
            continue
        if stripped.startswith("## "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(stripped[3:]), styles["h2"]))
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(stripped[4:]), styles["h3"]))
            continue
        bullet_match = re.match(r"^[-*]\s+(.+)$", stripped)
        number_match = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if bullet_match or number_match:
            flush_paragraph()
            if bullet_match:
                prefix, value = "•", bullet_match.group(1)
            else:
                prefix, value = f"{number_match.group(1)}.", number_match.group(2)
            story.append(
                Paragraph(f"{prefix}&nbsp;&nbsp;{inline_markup(value)}", styles["list"])
            )
            continue
        paragraph_lines.append(stripped.rstrip("  "))
    flush_paragraph()
    return story


def build_pdf():
    register_fonts()
    styles = build_styles()
    lines = SOURCE_FILE.read_text(encoding="utf-8").splitlines()
    story = parse_markdown(lines, styles)
    document = SimpleDocTemplate(
        str(OUTPUT_FILE),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=19 * mm,
        title="Eggie DocuFlow OCR 使用说明",
        author="Eggie DocuFlow",
        subject="OCR 配置、隐私、费用和责任边界说明",
    )
    document.build(
        story,
        onFirstPage=page_decorations,
        onLaterPages=page_decorations,
    )
    return OUTPUT_FILE


if __name__ == "__main__":
    print(build_pdf())
