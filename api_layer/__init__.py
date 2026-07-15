"""文档外部服务的统一入口。

图形界面和现有文档处理只依赖这里公开的函数，以后增加新的 OCR
平台或 PDF 比对时，不需要改动原有界面和文档处理流程。
"""

from api_layer.config import (
    PROVIDER_LABELS,
    delete_credentials,
    get_config_file,
    is_provider_configured,
    load_credentials,
    save_credentials,
)
from api_layer.document import (
    extract_document_to_files,
    inspect_pdf,
    process_document_with_ocr,
)

__all__ = [
    "PROVIDER_LABELS",
    "delete_credentials",
    "extract_document_to_files",
    "get_config_file",
    "inspect_pdf",
    "is_provider_configured",
    "load_credentials",
    "process_document_with_ocr",
    "save_credentials",
]
