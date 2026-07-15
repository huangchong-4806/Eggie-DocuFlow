import tempfile
import time
from pathlib import Path

from core.classifier import CONTRACT, INVOICE, TABLE, UNKNOWN, confidence, detect_doc_type
from exporters.excel_exporter import export_invoice, export_tables
from exporters.text_exporter import export_text
from exporters.word_exporter import export_contract
from parsers.contract_parser import parse_contract
from parsers.invoice_parser import parse_invoice
from parsers.table_parser import parse_tables
from parsers.text_parser import parse_text
from utils.file_helper import available_output_path, publish_output, temporary_output
from utils.logger import SessionLogger
from utils.pdf_helper import extract_text, validate_pdf


def _ocr_invoice(extraction):
    from pdf_invoice_tool import TextBlock, parse_invoice_blocks

    blocks = []
    for page in extraction.pages:
        for block in page.blocks:
            x0, top, x1, _ = block.bbox
            blocks.append(
                TextBlock(
                    text=block.text,
                    page=page.page_number,
                    x0=float(x0) * 600,
                    top=float(top) * 842,
                    x1=float(x1) * 600,
                )
            )
    return parse_invoice_blocks(blocks)


def _ocr_tables(extraction):
    from parsers.table_parser import valid_table

    for page in extraction.pages:
        page_blocks = sorted(
            (block for block in page.blocks if str(block.text).strip()),
            key=lambda block: (float(block.bbox[1]), float(block.bbox[0])),
        )
        lines = []
        for block in page_blocks:
            if not lines:
                lines.append([block])
                continue
            previous_top = sum(item.bbox[1] for item in lines[-1]) / len(lines[-1])
            tolerance = max(0.006, (block.bbox[3] - block.bbox[1]) * 0.55)
            if abs(block.bbox[1] - previous_top) <= tolerance:
                lines[-1].append(block)
            else:
                lines.append([block])

        rows = []
        for line in lines:
            values = []
            current = []
            previous_right = None
            for block in sorted(line, key=lambda item: item.bbox[0]):
                if previous_right is not None and block.bbox[0] - previous_right > 0.035:
                    values.append(" ".join(current).strip())
                    current = []
                current.append(str(block.text).strip())
                previous_right = block.bbox[2]
            if current:
                values.append(" ".join(current).strip())
            if len(values) == 1:
                import re

                split_values = [
                    value.strip()
                    for value in re.split(r"\t+|\s{2,}", values[0])
                    if value.strip()
                ]
                values = split_values or values
            if len(values) >= 2:
                rows.append(values)
        table = valid_table(rows)
        if table:
            yield page.page_number, 1, table


def _export_ocr_text(text_file, output_file, detected_type):
    temporary_file = temporary_output(output_file)
    try:
        with open(temporary_file, "w", encoding="utf-8") as output:
            output.write(f"文档类型：{detected_type}\n")
            output.write("结果说明：已完成 OCR 文字提取，但未生成可靠的结构化表格。\n\n")
            with open(text_file, encoding="utf-8") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), ""):
                    output.write(chunk)
        return publish_output(temporary_file, output_file)
    finally:
        Path(temporary_file).unlink(missing_ok=True)


def route_document(
    doc_type,
    pdf_file,
    text_file,
    output_dir,
    work_folder,
    progress_callback,
    extraction=None,
):
    stem = Path(pdf_file).stem
    if doc_type == INVOICE:
        output_file = available_output_path(output_dir / f"{stem}_发票结构化.xlsx")
        if extraction is not None and extraction.cloud_page_count:
            try:
                invoice = _ocr_invoice(extraction)
            except ValueError:
                fallback = available_output_path(output_dir / f"{stem}_发票_OCR文字.txt")
                return _export_ocr_text(text_file, fallback, INVOICE)
        else:
            invoice = parse_invoice(str(pdf_file), progress_callback)
        return export_invoice(invoice, str(output_file))
    if doc_type == CONTRACT:
        output_file = available_output_path(output_dir / f"{stem}_合同.docx")
        contract = parse_contract(text_file)
        return export_contract(contract, output_file, work_folder)
    if doc_type == TABLE:
        output_file = available_output_path(output_dir / f"{stem}_表格.xlsx")
        if extraction is not None and extraction.cloud_page_count:
            try:
                return export_tables(_ocr_tables(extraction), output_file)
            except ValueError:
                fallback = available_output_path(output_dir / f"{stem}_表格_OCR文字.txt")
                return _export_ocr_text(text_file, fallback, TABLE)
        return export_tables(parse_tables(pdf_file, progress_callback), output_file)
    output_file = available_output_path(output_dir / f"{stem}_无法分类.txt")
    text = parse_text(text_file)
    return export_text(text, output_file)


def process_document(
    pdf_file,
    output_dir=None,
    progress_callback=None,
    log_root=None,
    extractor=None,
):
    """Classify one PDF, route it once, and return the required result dictionary."""
    result = {"doc_type": UNKNOWN, "confidence": 0.0, "output_file": "", "status": "failed"}
    session = None
    started = time.monotonic()
    try:
        try:
            session = SessionLogger(log_root)
        except Exception:
            session = None
        pdf_file = validate_pdf(pdf_file)
        output_dir = Path(output_dir).expanduser().resolve() if output_dir else pdf_file.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        if session:
            session.info(f"文件加载: {pdf_file}, bytes={pdf_file.stat().st_size}")

        with tempfile.TemporaryDirectory(prefix="eggie-document-") as work_folder:
            text_file = Path(work_folder) / "extracted.txt"
            extraction = None
            if extractor is None:
                classification_text, page_count = extract_text(
                    pdf_file, text_file, progress_callback
                )
            else:
                extraction = extractor(pdf_file, text_file, progress_callback)
                classification_text = extraction.classification_text
                page_count = extraction.page_count
                result["ocr_used"] = bool(extraction.cloud_page_count)
                result["local_page_count"] = extraction.local_page_count
                result["cloud_page_count"] = extraction.cloud_page_count
                result["ocr_provider"] = extraction.provider
            if session:
                session.step(
                    f"PDF解析完成: pages={page_count}, "
                    f"sampled_chars={len(classification_text)}"
                )
                if extraction is not None:
                    session.info(
                        "OCR提取统计: "
                        f"provider={extraction.provider}, "
                        f"local_pages={extraction.local_page_count}, "
                        f"cloud_pages={extraction.cloud_page_count}"
                    )
                    for page in extraction.pages:
                        session.step(
                            "OCR页面结果: "
                            f"page={page.page_number}, method={page.method}, "
                            f"chars={len(page.text)}, blocks={len(page.blocks)}, "
                            f"request_id={page.request_id or '-'}, "
                            f"retries={page.retries}, "
                            f"elapsed={page.elapsed_seconds:.3f}s"
                        )

            doc_type = detect_doc_type(classification_text)
            confidence_value = confidence(classification_text, doc_type)
            result["doc_type"] = doc_type
            result["confidence"] = confidence_value
            if session:
                session.info(f"类型识别: {doc_type}, confidence={confidence_value}")
                session.step("分类完成")

            if session:
                session.info(f"路由分发: {doc_type}")
            result["output_file"] = route_document(
                doc_type,
                pdf_file,
                text_file,
                output_dir,
                work_folder,
                progress_callback,
                extraction,
            )
            result["status"] = "success"
            if session:
                session.step(
                    f"输出生成完成: {result['output_file']}, "
                    f"elapsed={time.monotonic() - started:.2f}s"
                )
    except Exception as error:
        result["error_message"] = f"{type(error).__name__}: {error}"
        if session:
            session.error(
                f"处理失败: {result['error_message']}, "
                f"elapsed={time.monotonic() - started:.2f}s",
                exc_info=True,
            )
    finally:
        if session:
            try:
                session.close()
            except Exception:
                pass
    return result
