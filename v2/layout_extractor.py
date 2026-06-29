from collections import Counter
from statistics import median

from parsers.table_parser import aligned_text_table, valid_table
from utils.pdf_helper import validate_pdf


def _words(page):
    try:
        return page.extract_words(extra_attrs=["fontname", "size"])
    except TypeError:
        return page.extract_words()


def _line_from_words(words):
    sizes = [float(word.get("size") or 10) for word in words]
    fonts = [word.get("fontname") or "" for word in words]
    x0 = min(float(word["x0"]) for word in words)
    x1 = max(float(word["x1"]) for word in words)
    top = min(float(word["top"]) for word in words)
    bottom = max(float(word["bottom"]) for word in words)
    return {
        "text": " ".join(word.get("text", "") for word in words).strip(),
        "x0": x0,
        "x1": x1,
        "top": top,
        "bottom": bottom,
        "size": median(sizes) if sizes else 10,
        "font": Counter(fonts).most_common(1)[0][0] if fonts else "",
    }


def _table_rows(table):
    rows = []
    for row in table.extract() or []:
        values = [None if value is None else str(value).strip() for value in row]
        if any(value not in (None, "") for value in values):
            rows.append(values)
    return rows if len(rows) >= 2 and max(len(row) for row in rows) >= 2 else []


def extract_contract_layout(pdf_file, progress_callback=None):
    try:
        import pdfplumber
    except ImportError as error:
        raise RuntimeError("缺少 PDF 版式解析组件 pdfplumber。") from error

    pdf_file = validate_pdf(pdf_file)
    pages = []
    with pdfplumber.open(pdf_file) as document:
        total = len(document.pages)
        for page_number, page in enumerate(document.pages, 1):
            lines = []
            current = []
            for word in sorted(_words(page), key=lambda item: (float(item["top"]), float(item["x0"]))):
                if current and abs(float(word["top"]) - float(current[-1]["top"])) > 3:
                    lines.append(_line_from_words(current))
                    current = []
                current.append(word)
            if current:
                lines.append(_line_from_words(current))

            tables = []
            try:
                page_tables = page.find_tables()
            except Exception:
                page_tables = []
            for table in page_tables:
                rows = _table_rows(table)
                if rows:
                    tables.append({"bbox": tuple(float(value) for value in table.bbox), "rows": rows})

            pages.append(
                {
                    "number": page_number,
                    "width": float(page.width),
                    "height": float(page.height),
                    "lines": lines,
                    "tables": tables,
                }
            )
            if progress_callback:
                progress_callback(page_number, total, f"正在提取第 {page_number} 页版式")
    return {"source_file": str(pdf_file), "pages": pages}


def extract_table_layout(pdf_file, progress_callback=None):
    try:
        import pdfplumber
    except ImportError as error:
        raise RuntimeError("缺少 PDF 表格版式解析组件 pdfplumber。") from error

    pdf_file = validate_pdf(pdf_file)
    tables = []
    with pdfplumber.open(pdf_file) as document:
        total = len(document.pages)
        for page_number, page in enumerate(document.pages, 1):
            page_tables = []
            try:
                page_tables = page.find_tables()
            except Exception:
                page_tables = []

            for table_number, table in enumerate(page_tables, 1):
                rows = valid_table(table.extract())
                if rows:
                    tables.append(
                        {
                            "page_number": page_number,
                            "table_number": table_number,
                            "page_width": float(page.width),
                            "page_height": float(page.height),
                            "bbox": tuple(float(value) for value in table.bbox),
                            "rows": rows,
                        }
                    )

            if not page_tables:
                rows = aligned_text_table(page.extract_text(layout=True) or "")
                if rows:
                    tables.append(
                        {
                            "page_number": page_number,
                            "table_number": 1,
                            "page_width": float(page.width),
                            "page_height": float(page.height),
                            "bbox": None,
                            "rows": rows,
                        }
                    )

            if progress_callback:
                progress_callback(page_number, total, f"正在提取第 {page_number} 页表格版式")
    return tables
