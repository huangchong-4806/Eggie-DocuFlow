import re
from pathlib import Path


MAX_PAGES = 100
SCANNED_MARKER = "[[SCANNED_PAGE:"


def validate_pdf(pdf_file):
    pdf_file = Path(pdf_file).expanduser().resolve()
    if pdf_file.suffix.lower() != ".pdf":
        raise ValueError("只支持 PDF 文件。")
    if not pdf_file.is_file():
        raise FileNotFoundError("PDF 文件不存在。")
    return pdf_file


def is_scanned_page(page, text):
    if len(re.sub(r"\s", "", text or "")) >= 20:
        return False
    page_area = max(float(page.width) * float(page.height), 1)
    return any(
        float(image.get("width", 0)) * float(image.get("height", 0))
        >= page_area * 0.25
        for image in page.images
    )


def extract_text(pdf_file, text_file, progress_callback=None):
    try:
        import pdfplumber
    except ImportError as error:
        raise RuntimeError("缺少 PDF 文本解析组件 pdfplumber。") from error

    sample_parts = []
    with pdfplumber.open(pdf_file) as document, open(text_file, "w", encoding="utf-8") as output:
        total = len(document.pages)
        if total == 0:
            raise ValueError("PDF 中没有可处理页面。")
        if total > MAX_PAGES:
            raise ValueError(f"PDF 超过 {MAX_PAGES} 页，请拆分后再处理。")

        for page_number, page in enumerate(document.pages, 1):
            page_text = page.extract_text(layout=True) or ""
            if is_scanned_page(page, page_text):
                page_text = f"{SCANNED_MARKER}{page_number}]]\n当前页无可提取文字，未启用 OCR。"
            output.write(f"\n\n=== 第 {page_number} 页 ===\n\n{page_text.rstrip()}\n")
            sample_parts.append(page_text[:4000])
            if progress_callback:
                progress_callback(page_number, total, f"正在读取第 {page_number} 页")
    return "\f".join(sample_parts), total
