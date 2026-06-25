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
from utils.file_helper import available_output_path
from utils.logger import SessionLogger
from utils.pdf_helper import extract_text, validate_pdf


def route_document(doc_type, pdf_file, text_file, output_dir, work_folder, progress_callback):
    stem = Path(pdf_file).stem
    if doc_type == INVOICE:
        output_file = available_output_path(output_dir / f"{stem}_发票结构化.xlsx")
        invoice = parse_invoice(str(pdf_file), progress_callback)
        return export_invoice(invoice, str(output_file))
    if doc_type == CONTRACT:
        output_file = available_output_path(output_dir / f"{stem}_合同.docx")
        contract = parse_contract(text_file)
        return export_contract(contract, output_file, work_folder)
    if doc_type == TABLE:
        output_file = available_output_path(output_dir / f"{stem}_表格.xlsx")
        tables = parse_tables(pdf_file, progress_callback)
        return export_tables(tables, output_file)
    output_file = available_output_path(output_dir / f"{stem}_无法分类.txt")
    text = parse_text(text_file)
    return export_text(text, output_file)


def process_document(pdf_file, output_dir=None, progress_callback=None, log_root=None):
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
            classification_text, page_count = extract_text(
                pdf_file, text_file, progress_callback
            )
            if session:
                session.step(
                    f"PDF解析完成: pages={page_count}, "
                    f"sampled_chars={len(classification_text)}"
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
            )
            result["status"] = "success"
            if session:
                session.step(
                    f"输出生成完成: {result['output_file']}, "
                    f"elapsed={time.monotonic() - started:.2f}s"
                )
    except Exception as error:
        if session:
            session.error(
                f"处理失败: {type(error).__name__}: {error}, "
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
