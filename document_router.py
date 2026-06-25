import argparse
import json
import sys

from core.classifier import (
    CONTRACT,
    DOC_TYPES,
    INVOICE,
    TABLE,
    UNKNOWN,
    _CONTRACT_KEYWORDS,
    _INVOICE_KEYWORDS,
    _TABLE_HEADERS,
    _detect_single_type,
    _detection_text,
    _keyword_hits,
    _table_features,
    confidence as _confidence,
    detect_doc_type,
)
from core.document_router import process_document, route_document as _route_document
from exporters.excel_exporter import export_tables
from exporters.text_exporter import export_text
from exporters.word_exporter import (
    CONTENT_TYPES as _CONTENT_TYPES,
    DOC_END as _DOC_END,
    DOC_START as _DOC_START,
    ROOT_RELS as _ROOT_RELS,
    export_contract,
)
from parsers.contract_parser import PAGE_HEADING as _PAGE_HEADING, parse_contract
from parsers.table_parser import (
    aligned_text_table as _aligned_text_table,
    excel_safe as _excel_safe,
    parse_tables,
    valid_table as _valid_table,
)
from parsers.text_parser import parse_text
from utils.file_helper import (
    INVALID_XML_CHARS as _INVALID_XML_CHARS,
    available_output_path as _available_output_path,
    publish_output as _publish_output,
    temporary_output as _temporary_output,
)
from utils.logger import (
    STEP_LEVEL,
    SessionLogger as _SessionLogger,
    clean_old_logs as _clean_old_logs,
    default_log_root as _default_log_root,
    export_logs,
)
from utils.pdf_helper import (
    MAX_PAGES,
    SCANNED_MARKER as _SCANNED_MARKER,
    extract_text as _extract_text,
    is_scanned_page as _is_scanned_page,
    validate_pdf as _validate_pdf,
)


def _write_contract_docx(text_file, output_file, work_folder):
    return export_contract(parse_contract(text_file), output_file, work_folder)


def _write_table_workbook(pdf_file, output_file, progress_callback=None):
    return export_tables(parse_tables(pdf_file, progress_callback), output_file)


def _write_unknown_text(text_file, output_file):
    return export_text(parse_text(text_file), output_file)


def _self_check():
    assert detect_doc_type("增值税发票 发票号码 123 税号 456 金额 100 税额 13") == INVOICE
    assert detect_doc_type("采购合同 甲方：甲公司 乙方：乙公司 第一条 合同条款") == CONTRACT
    assert detect_doc_type("名称  数量  单价  金额\n苹果  2  3.00  6.00\n梨  1  4.00  4.00") == TABLE
    assert detect_doc_type("这是一份普通说明文字") == UNKNOWN
    assert detect_doc_type("发票 金额 税额 合同 甲方 乙方 协议") == UNKNOWN
    assert detect_doc_type("发 票 发 票 号 码 税 号 金 额 税 额") == INVOICE
    assert detect_doc_type(
        "发票 发票号码 税号 金额 税额\f采购合同 甲方 乙方 合同条款"
    ) == UNKNOWN
    print("document_router self-check: OK")


def _cli_progress(value, total, message):
    print(f"[{value}/{total}] {message}", file=sys.stderr, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="EggieExcelTool 文档智能路由 MVP")
    parser.add_argument("pdf", nargs="?", help="待处理 PDF 文件")
    parser.add_argument("-o", "--output-dir", help="输出文件夹，默认与 PDF 相同")
    parser.add_argument("--log-dir", help="日志目录")
    parser.add_argument("--export-logs", metavar="ZIP", help="导出日志 ZIP")
    parser.add_argument("--self-check", action="store_true", help="运行内置分类检查")
    args = parser.parse_args(argv)

    if args.self_check:
        _self_check()
        return 0
    if args.export_logs:
        print(export_logs(args.export_logs, args.log_dir))
        return 0
    if not args.pdf:
        parser.error("请提供 PDF 文件，或使用 --self-check / --export-logs。")

    print(f"正在处理：{args.pdf}", file=sys.stderr, flush=True)
    result = process_document(
        args.pdf,
        args.output_dir,
        progress_callback=_cli_progress,
        log_root=args.log_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "success":
        print(f"处理完成：{result['output_file']}", file=sys.stderr)
    else:
        print(
            f"处理失败，请查看日志：{args.log_dir or _default_log_root()}",
            file=sys.stderr,
        )
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
