import re
import unicodedata

from utils.pdf_helper import SCANNED_MARKER


INVOICE = "INVOICE"
CONTRACT = "CONTRACT"
TABLE = "TABLE"
UNKNOWN = "UNKNOWN"
DOC_TYPES = (INVOICE, CONTRACT, TABLE, UNKNOWN)

_INVOICE_KEYWORDS = (
    ("发票",),
    ("税号", "纳税人识别号", "统一社会信用代码"),
    ("发票号码",),
    ("金额", "价税合计"),
    ("税额", "税率"),
)
_CONTRACT_KEYWORDS = (("甲方",), ("乙方",), ("合同",), ("协议",), ("条款",))
_TABLE_HEADERS = (("数量",), ("单价",), ("金额",), ("规格",), ("单位",))


def _keyword_hits(text, keyword_groups):
    return sum(any(keyword in text for keyword in group) for group in keyword_groups)


def _detection_text(text):
    text = unicodedata.normalize("NFKC", str(text or ""))
    return re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", text)


def _table_features(text):
    text = unicodedata.normalize("NFKC", str(text or ""))
    header_hits = _keyword_hits(text, _TABLE_HEADERS)
    aligned_rows = 0
    numeric_rows = 0
    for line in text.splitlines():
        columns = [value for value in re.split(r"\t+|\s{2,}", line.strip()) if value]
        number_count = len(
            re.findall(r"(?<![A-Za-z0-9_])-?\d[\d,]*(?:\.\d+)?%?", line)
        )
        if len(columns) >= 3 and number_count >= 2:
            aligned_rows += 1
        if number_count >= 3:
            numeric_rows += 1
    return header_hits, aligned_rows, numeric_rows


def _detect_single_type(text):
    keyword_text = _detection_text(text)
    invoice_hits = _keyword_hits(keyword_text, _INVOICE_KEYWORDS)
    contract_hits = _keyword_hits(keyword_text, _CONTRACT_KEYWORDS)
    table_headers, aligned_rows, numeric_rows = _table_features(text)

    if invoice_hits >= 3 and contract_hits >= 2:
        return UNKNOWN
    if invoice_hits >= 3 and "发票" in keyword_text:
        return INVOICE
    if contract_hits >= 2 and ("合同" in keyword_text or "协议" in keyword_text):
        return CONTRACT
    if (table_headers >= 3 and (aligned_rows or numeric_rows)) or aligned_rows >= 3:
        return TABLE
    return UNKNOWN


def detect_doc_type(text):
    """Return INVOICE, CONTRACT, TABLE, or UNKNOWN for extracted PDF text."""
    text = str(text or "")
    if not text.strip() or SCANNED_MARKER in text:
        return UNKNOWN

    page_types = {
        _detect_single_type(page_text)
        for page_text in text.split("\f")
        if page_text.strip()
    } - {UNKNOWN}
    if len(page_types) > 1:
        return UNKNOWN
    if page_types:
        return next(iter(page_types))
    return _detect_single_type(text.replace("\f", "\n"))


def confidence(text, doc_type):
    if doc_type == UNKNOWN:
        return 0.0
    keyword_text = _detection_text(text)
    if doc_type == INVOICE:
        hits = _keyword_hits(keyword_text, _INVOICE_KEYWORDS)
        return round(min(0.95, 0.5 + hits * 0.09), 2)
    if doc_type == CONTRACT:
        hits = _keyword_hits(keyword_text, _CONTRACT_KEYWORDS)
        return round(min(0.95, 0.5 + hits * 0.09), 2)
    headers, aligned_rows, numeric_rows = _table_features(text)
    return round(min(0.95, 0.5 + headers * 0.07 + min(aligned_rows + numeric_rows, 8) * 0.03), 2)
