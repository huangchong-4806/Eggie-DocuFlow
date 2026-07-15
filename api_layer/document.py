import io
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

from api_layer.config import PROVIDER_LABELS
from api_layer.models import (
    DocumentExtraction,
    ExtractionFiles,
    PageText,
    PdfInspection,
    TextBlock,
)
from api_layer.providers import OCRProviderError, create_provider
from utils.pdf_helper import MAX_PAGES, is_scanned_page, validate_pdf


MAX_IMAGE_BYTES = 3_500_000
MAX_IMAGE_EDGE = 4096


def inspect_pdf(pdf_file):
    try:
        import pdfplumber
    except ImportError as error:
        raise RuntimeError("缺少 PDF 文字解析组件 pdfplumber。") from error
    source = validate_pdf(pdf_file)
    scanned_pages = []
    with pdfplumber.open(source) as document:
        page_count = len(document.pages)
        if page_count == 0:
            raise ValueError("PDF 中没有可处理页面。")
        if page_count > MAX_PAGES:
            raise ValueError(f"PDF 超过 {MAX_PAGES} 页，请拆分后再处理。")
        for page_number, page in enumerate(document.pages, 1):
            text = page.extract_text(layout=True) or ""
            if is_scanned_page(page, text):
                scanned_pages.append(page_number)
    return PdfInspection(str(source), page_count, tuple(scanned_pages))


def _local_page(page, page_number, text, elapsed_seconds):
    blocks = []
    try:
        words = page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
    except TypeError:
        words = page.extract_words() or []
    width = max(float(page.width), 1.0)
    height = max(float(page.height), 1.0)
    for word in words:
        value = str(word.get("text", "")).strip()
        if not value:
            continue
        blocks.append(
            TextBlock(
                text=value,
                bbox=(
                    max(0.0, min(1.0, float(word.get("x0", 0)) / width)),
                    max(0.0, min(1.0, float(word.get("top", 0)) / height)),
                    max(0.0, min(1.0, float(word.get("x1", 0)) / width)),
                    max(0.0, min(1.0, float(word.get("bottom", 0)) / height)),
                ),
            )
        )
    return PageText(
        page_number=page_number,
        text=text,
        method="local_text",
        blocks=tuple(blocks),
        width=width,
        height=height,
        elapsed_seconds=elapsed_seconds,
    )


def _render_page_image(pdfium_document, page_index):
    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError("缺少图片处理组件 Pillow。") from error
    page = pdfium_document[page_index]
    image = None
    try:
        width = max(float(page.get_width()), 1.0)
        height = max(float(page.get_height()), 1.0)
        scale = min(220 / 72, MAX_IMAGE_EDGE / max(width, height))
        bitmap = page.render(scale=max(scale, 1.0))
        image = bitmap.to_pil().convert("RGB")
    finally:
        page.close()

    try:
        if max(image.size) > MAX_IMAGE_EDGE:
            ratio = MAX_IMAGE_EDGE / max(image.size)
            resized_image = image.resize(
                (max(15, int(image.width * ratio)), max(15, int(image.height * ratio))),
                Image.Resampling.LANCZOS,
            )
            image.close()
            image = resized_image
        quality = 90
        while True:
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=quality, optimize=True)
            data = buffer.getvalue()
            if len(data) <= MAX_IMAGE_BYTES:
                return data, image.width, image.height
            if quality > 72:
                quality -= 6
                continue
            ratio = 0.85
            resized_image = image.resize(
                (max(15, int(image.width * ratio)), max(15, int(image.height * ratio))),
                Image.Resampling.LANCZOS,
            )
            image.close()
            image = resized_image
            quality = 86
            if min(image.size) <= 15 and len(data) > MAX_IMAGE_BYTES:
                raise ValueError("PDF 页面图片过大，无法安全上传识别。")
    finally:
        if image is not None:
            image.close()


def _recognize_with_retry(provider, image_bytes, page_number, width, height):
    retries = 0
    while True:
        try:
            result = provider.recognize_image(
                image_bytes,
                page_number,
                width,
                height,
            )
            if retries:
                result = PageText(
                    page_number=result.page_number,
                    text=result.text,
                    method=result.method,
                    blocks=result.blocks,
                    width=result.width,
                    height=result.height,
                    request_id=result.request_id,
                    elapsed_seconds=result.elapsed_seconds,
                    retries=retries,
                )
            return result
        except OCRProviderError as error:
            if not error.retriable or retries >= 1:
                raise
            retries += 1
            time.sleep(0.8)


def extract_document(pdf_file, provider_name, progress_callback=None):
    try:
        import pdfplumber
        import pypdfium2 as pdfium
    except ImportError as error:
        raise RuntimeError("缺少 PDF 解析或图片处理组件。") from error
    if provider_name not in PROVIDER_LABELS:
        raise ValueError("不支持的 OCR 服务平台。")
    source = validate_pdf(pdf_file)
    provider = None
    pages = []
    started_at = datetime.now().isoformat(timespec="seconds")
    pdfium_document = pdfium.PdfDocument(str(source))
    try:
        with pdfplumber.open(source) as document:
            total = len(document.pages)
            if total == 0:
                raise ValueError("PDF 中没有可处理页面。")
            if total > MAX_PAGES:
                raise ValueError(f"PDF 超过 {MAX_PAGES} 页，请拆分后再处理。")
            for page_number, page in enumerate(document.pages, 1):
                page_started = time.monotonic()
                text = page.extract_text(layout=True) or ""
                if is_scanned_page(page, text):
                    if provider is None:
                        provider = create_provider(provider_name)
                    if progress_callback:
                        progress_callback(
                            page_number - 1,
                            total,
                            f"正在使用 {provider.label} 识别第 {page_number} 页",
                        )
                    image_bytes, width, height = _render_page_image(
                        pdfium_document,
                        page_number - 1,
                    )
                    page_result = _recognize_with_retry(
                        provider,
                        image_bytes,
                        page_number,
                        width,
                        height,
                    )
                else:
                    page_result = _local_page(
                        page,
                        page_number,
                        text,
                        time.monotonic() - page_started,
                    )
                pages.append(page_result)
                if progress_callback:
                    method = "本机文字" if page_result.method == "local_text" else "云 OCR"
                    progress_callback(
                        page_number,
                        total,
                        f"第 {page_number} 页已完成（{method}）",
                    )
    finally:
        pdfium_document.close()
    return DocumentExtraction(
        source_file=str(source),
        provider=provider_name if any(page.method == "cloud_ocr" for page in pages) else "local",
        pages=tuple(pages),
        started_at=started_at,
    )


def _output_paths(output_folder, stem):
    output_folder = Path(output_folder).expanduser().resolve()
    output_folder.mkdir(parents=True, exist_ok=True)
    for number in range(10000):
        suffix = "" if number == 0 else f"_{number}"
        base = output_folder / f"{stem}_文字提取{suffix}"
        paths = (
            output_folder / f"{base.name}.txt",
            output_folder / f"{base.name}.json",
            output_folder / f"{base.name}_日志.txt",
        )
        if not any(path.exists() for path in paths):
            return paths
    raise FileExistsError("无法生成不重复的文字提取结果名称。")


def _atomic_write(path, content):
    path = Path(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}-",
        suffix=path.suffix,
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o644)
        os.link(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    return str(path)


def _log_text(extraction, text_file, json_file, log_file):
    provider_label = (
        PROVIDER_LABELS.get(extraction.provider, "未调用云 OCR")
        if extraction.provider != "local"
        else "未调用云 OCR"
    )
    lines = [
        "Eggie DocuFlow PDF 文字提取日志",
        f"开始时间：{extraction.started_at}",
        f"来源文件：{extraction.source_file}",
        f"服务平台：{provider_label}",
        "隐私范围：文本页仅本机读取；仅扫描图片页调用用户选择的云 OCR。",
        "=" * 60,
        "匹配结果：",
    ]
    for page in extraction.pages:
        lines.append(
            f"page={page.page_number} method={page.method} "
            f"chars={len(page.text)} blocks={len(page.blocks)} "
            f"request_id={page.request_id or '-'} retries={page.retries} "
            f"elapsed={page.elapsed_seconds:.3f}s"
        )
    lines.extend(
        [
            "",
            "计算过程：",
            f"page_count={extraction.page_count}",
            f"local_page_count={extraction.local_page_count}",
            f"cloud_page_count={extraction.cloud_page_count}",
            f"character_count={sum(len(page.text) for page in extraction.pages)}",
            f"block_count={sum(len(page.blocks) for page in extraction.pages)}",
            "",
            "文件生成状态：",
            f"text_file={text_file}",
            f"json_file={json_file}",
            f"log_file={log_file}",
            "secrets_written=false",
            "document_text_written_to_log=false",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_extraction_bundle(extraction, text_path, json_path, log_path):
    final_paths = tuple(Path(path) for path in (text_path, json_path, log_path))
    published = []
    with tempfile.TemporaryDirectory(
        prefix=".eggie-extraction-",
        dir=final_paths[0].parent,
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        temporary_paths = tuple(
            temporary_root / path.name for path in final_paths
        )
        _atomic_write(temporary_paths[0], extraction.full_text)
        _atomic_write(
            temporary_paths[1],
            json.dumps(extraction.to_dict(), ensure_ascii=False, indent=2) + "\n",
        )
        _atomic_write(
            temporary_paths[2],
            _log_text(
                extraction,
                str(final_paths[0]),
                str(final_paths[1]),
                str(final_paths[2]),
            ),
        )
        try:
            for temporary_path, final_path in zip(temporary_paths, final_paths):
                os.link(temporary_path, final_path)
                published.append(final_path)
        except Exception:
            for final_path in published:
                final_path.unlink(missing_ok=True)
            raise

    return ExtractionFiles(
        source_file=extraction.source_file,
        text_file=str(final_paths[0]),
        json_file=str(final_paths[1]),
        log_file=str(final_paths[2]),
        provider=extraction.provider,
        page_count=extraction.page_count,
        local_page_count=extraction.local_page_count,
        cloud_page_count=extraction.cloud_page_count,
        pages=extraction.pages,
    )


def extract_document_to_files(pdf_file, output_folder, provider_name, progress_callback=None):
    extraction = extract_document(pdf_file, provider_name, progress_callback)
    text_path, json_path, log_path = _output_paths(
        output_folder,
        Path(extraction.source_file).stem,
    )
    return _write_extraction_bundle(extraction, text_path, json_path, log_path)


class UnifiedDocumentExtractor:
    def __init__(self, provider_name):
        self.provider_name = provider_name

    def __call__(self, pdf_file, text_file, progress_callback=None):
        extraction = extract_document(pdf_file, self.provider_name, progress_callback)
        Path(text_file).write_text(extraction.full_text, encoding="utf-8")
        return extraction


def process_document_with_ocr(
    pdf_file,
    output_dir=None,
    provider_name="baidu",
    progress_callback=None,
    log_root=None,
):
    from core.document_router import process_document

    return process_document(
        pdf_file,
        output_dir,
        progress_callback,
        log_root,
        extractor=UnifiedDocumentExtractor(provider_name),
    )
