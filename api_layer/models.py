from dataclasses import dataclass, field


@dataclass(frozen=True)
class TextBlock:
    text: str
    bbox: tuple = (0.0, 0.0, 0.0, 0.0)
    confidence: float = None

    def to_dict(self):
        payload = {
            "text": self.text,
            "bbox": [round(float(value), 6) for value in self.bbox],
        }
        if self.confidence is not None:
            payload["confidence"] = round(float(self.confidence), 6)
        return payload


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str
    method: str
    blocks: tuple = ()
    width: float = 0.0
    height: float = 0.0
    request_id: str = ""
    elapsed_seconds: float = 0.0
    retries: int = 0

    def to_dict(self):
        return {
            "page_number": self.page_number,
            "method": self.method,
            "text": self.text,
            "width": self.width,
            "height": self.height,
            "request_id": self.request_id,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "retries": self.retries,
            "blocks": [block.to_dict() for block in self.blocks],
        }


@dataclass(frozen=True)
class DocumentExtraction:
    source_file: str
    provider: str
    pages: tuple
    started_at: str

    @property
    def page_count(self):
        return len(self.pages)

    @property
    def local_page_count(self):
        return sum(page.method == "local_text" for page in self.pages)

    @property
    def cloud_page_count(self):
        return sum(page.method == "cloud_ocr" for page in self.pages)

    @property
    def classification_text(self):
        return "\f".join(page.text[:4000] for page in self.pages)

    @property
    def full_text(self):
        parts = []
        for page in self.pages:
            parts.append(f"=== 第 {page.page_number} 页 ===\n\n{page.text.rstrip()}")
        return "\n\n".join(parts).rstrip() + "\n"

    def to_dict(self):
        return {
            "schema_version": 1,
            "source_file": self.source_file,
            "provider": self.provider,
            "started_at": self.started_at,
            "page_count": self.page_count,
            "local_page_count": self.local_page_count,
            "cloud_page_count": self.cloud_page_count,
            "pages": [page.to_dict() for page in self.pages],
        }


@dataclass(frozen=True)
class PdfInspection:
    source_file: str
    page_count: int
    scanned_pages: tuple = ()


@dataclass(frozen=True)
class ExtractionFiles:
    source_file: str
    text_file: str
    json_file: str
    log_file: str
    provider: str
    page_count: int
    local_page_count: int
    cloud_page_count: int
    pages: tuple = field(default_factory=tuple)
