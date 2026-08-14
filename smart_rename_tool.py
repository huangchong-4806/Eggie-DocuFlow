import hashlib
import re
import tempfile
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

from api_layer.document import extract_document
from batch_rename_tool import preview_explicit_renames
from core.classifier import CONTRACT, INVOICE, UNKNOWN, detect_doc_type
from core.document_router import invoice_from_extraction
from pdf_invoice_tool import extract_invoice
from utils.pdf_helper import extract_text


@dataclass(frozen=True)
class SmartRenameSuggestion:
    source_file: str
    document_type: str
    suggested_name: str
    reason: str = ""
    duplicate_of: str = ""


@dataclass(frozen=True)
class SmartRenameResult:
    previews: tuple
    suggestions: tuple

    @property
    def metadata_by_source(self):
        return {
            suggestion.source_file: {
                "识别类型": suggestion.document_type,
                "识别说明": suggestion.reason or "识别成功",
                "重复文件": suggestion.duplicate_of or "否",
            }
            for suggestion in self.suggestions
        }


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_component(value, limit=48):
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = re.sub(r"[\\/:*?\"<>|\x00]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" ._-")
    return value[:limit].rstrip(" ._-")


def _date_token(value):
    match = re.search(r"(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})", str(value or ""))
    if match:
        return f"{int(match.group(1)):04d}{int(match.group(2)):02d}{int(match.group(3)):02d}"
    match = re.search(r"(?<!\d)(20\d{6})(?!\d)", str(value or ""))
    return match.group(1) if match else ""


def _short_company(value):
    company = _safe_component(value)
    for suffix in ("股份有限公司", "有限责任公司", "有限公司", "公司"):
        if company.endswith(suffix) and len(company) > len(suffix) + 1:
            company = company[: -len(suffix)]
            break
    return company


def _contract_parts(text):
    lines = [
        _safe_component(line)
        for line in str(text or "").splitlines()
        if _safe_component(line) and not line.strip().startswith("=== 第")
    ]
    title = next(
        (
            line for line in lines[:30]
            if ("合同" in line or "协议" in line)
            and not line.startswith(("合同编号", "协议编号"))
        ),
        "",
    )
    date_value = _date_token(text)
    return title, date_value


def _local_text(source):
    with tempfile.TemporaryDirectory(prefix="eggie-smart-rename-") as folder:
        text_file = Path(folder) / "text.txt"
        classification_text, _page_count = extract_text(source, text_file)
        return classification_text, text_file.read_text(encoding="utf-8")


def _suggest_one(source, use_ocr, provider_name):
    extraction = None
    if use_ocr:
        extraction = extract_document(source, provider_name)
        classification_text = extraction.classification_text
        full_text = extraction.full_text
    else:
        classification_text, full_text = _local_text(source)
    document_type = detect_doc_type(classification_text)

    if document_type == INVOICE:
        invoice = invoice_from_extraction(extraction) if extraction is not None else extract_invoice(source)
        header = invoice.header
        invoice_date = _date_token(header.get("开票日期", ""))
        seller = _short_company(header.get("销售方名称", ""))
        total = header.get("价税合计（小写）")
        total_text = f"{total:.2f}" if total is not None else ""
        if not all((invoice_date, seller, total_text)):
            return INVOICE, "", "发票关键信息不完整，已保持原文件名"
        return INVOICE, f"{invoice_date}_{seller}_{total_text}", ""

    if document_type == CONTRACT:
        title, contract_date = _contract_parts(full_text)
        if not title or not contract_date:
            return CONTRACT, "", "合同标题或日期不完整，已保持原文件名"
        return CONTRACT, f"{contract_date}_{title}", ""

    return document_type or UNKNOWN, "", "未可靠识别为发票或合同，已保持原文件名"


def suggest_smart_renames(
    files,
    use_ocr=False,
    provider_name="baidu",
    progress_callback=None,
):
    sources = tuple(Path(path).expanduser().resolve() for path in files)
    seen_hashes = {}
    suggestions = []
    pairs = []
    for index, source in enumerate(sources, 1):
        if progress_callback:
            progress_callback(index - 1, len(sources), f"正在识别：{source.name}")
        duplicate_of = ""
        reason = ""
        document_type = UNKNOWN
        stem = ""
        try:
            if source.suffix.lower() != ".pdf":
                raise ValueError("智能识别命名当前只支持 PDF")
            digest = _file_hash(source)
            if digest in seen_hashes:
                duplicate_of = str(seen_hashes[digest])
            else:
                seen_hashes[digest] = source
            document_type, stem, reason = _suggest_one(source, use_ocr, provider_name)
        except Exception as error:
            reason = f"{type(error).__name__}: {error}，已保持原文件名"
        target = source.with_name(f"{_safe_component(stem)}{source.suffix}") if stem else source
        pairs.append((str(source), str(target)))
        suggestions.append(
            SmartRenameSuggestion(
                str(source),
                document_type,
                target.name,
                reason,
                duplicate_of,
            )
        )
        if progress_callback:
            progress_callback(index, len(sources), f"已识别：{source.name}")

    previews = list(preview_explicit_renames(pairs))
    for index, suggestion in enumerate(suggestions):
        preview = previews[index]
        message_parts = [part for part in (preview.message, suggestion.reason) if part]
        if suggestion.duplicate_of:
            message_parts.append(f"内容与 {Path(suggestion.duplicate_of).name} 相同")
        message = "；".join(message_parts)
        if message:
            status = preview.status
            if not preview.blocked and not preview.will_rename:
                status = "保持原名"
            elif not preview.blocked and suggestion.duplicate_of:
                status = "重复内容"
            previews[index] = replace(preview, status=status, message=message)
    return SmartRenameResult(tuple(previews), tuple(suggestions))
