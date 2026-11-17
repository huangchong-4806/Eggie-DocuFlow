from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from api_layer.models import OCRApproval
from utils.pdf_helper import open_pdf
from utils.source_snapshot import PreviewChanged, reviewed_stream
from api_layer import inspect_pdf, process_document_with_ocr
from core.document_router import process_document
from utils.file_helper import available_output_path
from layout_batch.batch_engine import BatchEngine


@dataclass(frozen=True)
class BatchPreview:
    source_file: str
    page_count: int = 0
    scanned_page_count: int = 0
    suggested_action: str = "本机自动识别"
    error_message: str = ""
    scanned_pages: tuple = ()
    digest: str = ""


@dataclass(frozen=True)
class BatchRunResult:
    results: tuple
    log_file: str
    warning: str = ""

    @property
    def successful(self):
        return tuple(item for item in self.results if item.get("status") == "success")

    @property
    def failed(self):
        return tuple(item for item in self.results if item.get("status") == "failed")

    @property
    def unprocessed(self):
        return tuple(item for item in self.results if item.get("status") == "unprocessed")


def discover_pdf_files(folder, recursive=False):
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise NotADirectoryError(f"输入文件夹不存在：{folder}")
    candidates = folder.rglob("*") if recursive else folder.iterdir()
    return tuple(
        sorted(
            path for path in candidates
            if path.is_file() and path.suffix.lower() == ".pdf"
        )
    )


def inspect_pdf_files(pdf_files, progress_callback=None):
    previews = []
    files = tuple(Path(path).expanduser().resolve() for path in pdf_files)
    for index, source in enumerate(files, 1):
        if progress_callback:
            progress_callback(index - 1, len(files), f"正在检查：{source.name}")
        try:
            inspection = inspect_pdf(source)
            scanned_count = len(inspection.scanned_pages)
            action = "本机自动识别"
            if scanned_count:
                action = f"含 {scanned_count} 个扫描页，可选云 OCR"
            previews.append(
                BatchPreview(
                    source_file=str(source),
                    page_count=inspection.page_count,
                    scanned_page_count=scanned_count,
                    suggested_action=action,
                    scanned_pages=inspection.scanned_pages,
                    digest=inspection.digest,
                )
            )
        except Exception as error:
            previews.append(
                BatchPreview(
                    source_file=str(source),
                    error_message=f"{type(error).__name__}: {error}",
                    suggested_action="无法处理",
                )
            )
        if progress_callback:
            progress_callback(index, len(files), f"已检查：{source.name}")
    return tuple(previews)


def _batch_log(output_folder, results, use_ocr, provider_name):
    output_folder = Path(output_folder).expanduser().resolve()
    log_file = available_output_path(
        output_folder / f"批量处理日志_{datetime.now():%Y%m%d_%H%M%S}.txt"
    )
    success_count = sum(item.get("status") == "success" for item in results)
    with log_file.open("w", encoding="utf-8") as handle:
        handle.write("Eggie DocuFlow 批量处理日志\n")
        handle.write(f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n")
        handle.write(f"云 OCR：{'已启用' if use_ocr else '未启用'}\n")
        handle.write(f"OCR 平台：{provider_name if use_ocr else '-'}\n")
        handle.write(f"文件总数：{len(results)}\n")
        handle.write(f"成功数量：{success_count}\n")
        handle.write(f"失败数量：{sum(item.get('status') == 'failed' for item in results)}\n")
        handle.write(f"未处理数量：{sum(item.get('status') == 'unprocessed' for item in results)}\n\n")
        handle.write("匹配结果：\n")
        for item in results:
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            handle.write(
                f"source_file={data.get('source_file', '')} "
                f"doc_type={item.get('doc_type', 'UNKNOWN')} "
                f"status={item.get('status', 'failed')} "
                f"output_file={item.get('output_file', '')} "
                f"error={data.get('error_message', '')} warning={data.get('warning', '')} "
                f"结果类型={'仅提取文字' if data.get('text_only') else item.get('doc_type', '')}\n"
            )
        handle.write("\n文件生成状态：\n")
        handle.write(f"log_file={log_file}\n")
    return str(log_file)


def process_pdf_files(
    pdf_files,
    output_folder,
    use_ocr=False,
    provider_name="baidu",
    progress_callback=None,
    expected_previews=None,
):
    files = tuple(Path(path).expanduser().resolve() for path in pdf_files)
    if not files:
        raise ValueError("没有可处理的 PDF 文件。")
    output_folder = Path(output_folder).expanduser().resolve()
    output_folder.mkdir(parents=True, exist_ok=True)

    previews = {item.source_file: item for item in expected_previews or ()}

    def router(pdf_file, output_dir, progress_callback=None, log_root=None):
        kwargs = dict(progress_callback=progress_callback, log_root=log_root)
        preview = previews.get(str(pdf_file))
        if expected_previews is not None and (preview is None or not preview.digest or preview.error_message):
            return {"status": "unprocessed", "error_message": "文件没有通过预览，请重新检查。"}
        try:
            if use_ocr:
                approval = OCRApproval.from_preview(preview, provider_name) if preview else None
                return process_document_with_ocr(pdf_file, output_dir, provider_name=provider_name, approval=approval, **kwargs)
            if preview is not None:
                with reviewed_stream(pdf_file, preview) as (stream, _), open_pdf(stream) as document:
                    return process_document(pdf_file, output_dir, reviewed_document=document, **kwargs)
            return process_document(pdf_file, output_dir, **kwargs)
        except PreviewChanged as error:
            return {"status": "unprocessed", "error_message": str(error)}

    results = BatchEngine(
        router=router,
        max_workers=1 if use_ocr else 2,
        log_file=output_folder / "批量任务过程.log",
    ).process_files(
        files,
        output_folder,
        progress_callback=progress_callback,
    )
    try:
        log_file = _batch_log(output_folder, results, use_ocr, provider_name)
    except OSError as error:
        return BatchRunResult(tuple(results), "", f"汇总日志未写入：{error}")
    return BatchRunResult(tuple(results), log_file)
