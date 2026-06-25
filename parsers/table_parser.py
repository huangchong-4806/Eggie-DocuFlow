import re
import unicodedata

from utils.file_helper import INVALID_XML_CHARS


def excel_safe(value):
    if isinstance(value, str):
        value = INVALID_XML_CHARS.sub("", unicodedata.normalize("NFKC", value)).strip()
        if value.startswith(("=", "+", "-", "@")):
            return "'" + value
    return value


def valid_table(table):
    rows = []
    for row in table or []:
        values = [excel_safe(value) for value in (row or [])]
        while values and values[-1] in (None, ""):
            values.pop()
        if any(value not in (None, "") for value in values):
            rows.append(values)
    if len(rows) < 2:
        return []
    width = max(len(row) for row in rows)
    if width < 2:
        return []
    return [row + [None] * (width - len(row)) for row in rows]


def aligned_text_table(text):
    rows = []
    for line in (text or "").splitlines():
        values = [value.strip() for value in re.split(r"\t+|\s{2,}", line.strip()) if value.strip()]
        if len(values) >= 2:
            rows.append(values)
    return valid_table(rows)


def parse_tables(pdf_file, progress_callback=None):
    try:
        import pdfplumber
    except ImportError as error:
        raise RuntimeError("缺少 PDF 或 Excel 处理组件。") from error

    with pdfplumber.open(pdf_file) as document:
        total = len(document.pages)
        for page_number, page in enumerate(document.pages, 1):
            tables = [valid_table(table) for table in (page.extract_tables() or [])]
            tables = [table for table in tables if table]
            if not tables:
                fallback = aligned_text_table(page.extract_text(layout=True) or "")
                tables = [fallback] if fallback else []

            for page_table_number, table in enumerate(tables, 1):
                yield page_number, page_table_number, table
            if progress_callback:
                progress_callback(page_number, total, f"正在提取第 {page_number} 页表格")
