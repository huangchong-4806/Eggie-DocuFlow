import tempfile
from pathlib import Path

import document_router
from core.classifier import CONTRACT, TABLE, UNKNOWN, detect_doc_type
from utils.file_helper import available_output_path
from utils.pdf_helper import extract_text, validate_pdf
from v2.batch_engine import _v2_result
from v2.layout_exporters import export_contract_layout, export_table_layout
from v2.layout_extractor import extract_contract_layout, extract_table_layout


def process_layout_document(pdf_file, output_dir=None, progress_callback=None, log_root=None, style_template=None):
    result = {"doc_type": UNKNOWN, "data": {}, "output_file": "", "status": "failed"}
    try:
        pdf_file = validate_pdf(pdf_file)
        output_dir = Path(output_dir).expanduser().resolve() if output_dir else pdf_file.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="eggie-layout-") as work_folder:
            text_file = Path(work_folder) / "extracted.txt"
            classification_text, page_count = extract_text(pdf_file, text_file, progress_callback)
            doc_type = detect_doc_type(classification_text)

        if doc_type == CONTRACT:
            layout = extract_contract_layout(pdf_file, progress_callback)
            suffix = "_合同_正式样式.docx" if style_template == "formal_contract" else "_合同_版式.docx"
            output_file = available_output_path(output_dir / f"{pdf_file.stem}{suffix}")
            export_contract_layout(layout, output_file, style_template=style_template)
            result.update(
                {
                    "doc_type": CONTRACT,
                    "data": {
                        "source_file": str(pdf_file),
                        "pages": page_count,
                        "layout_restored": True,
                        "style_template": style_template or "",
                    },
                    "output_file": str(output_file),
                    "status": "success",
                }
            )
        elif doc_type == TABLE:
            tables = extract_table_layout(pdf_file, progress_callback)
            output_file = available_output_path(output_dir / f"{pdf_file.stem}_表格_版式.xlsx")
            export_table_layout(tables, output_file)
            result.update(
                {
                    "doc_type": TABLE,
                    "data": {"source_file": str(pdf_file), "tables": len(tables), "layout_restored": True},
                    "output_file": str(output_file),
                    "status": "success",
                }
            )
        else:
            return _v2_result(
                document_router.process_document(pdf_file, output_dir, progress_callback, log_root),
                pdf_file,
            )
    except Exception as error:
        result["data"] = {"source_file": str(pdf_file), "error_message": f"{type(error).__name__}: {error}"}
    return result
