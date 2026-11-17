import os
import re
import tempfile
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from operator import itemgetter
from pathlib import Path
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from utils.file_helper import available_output_path, publish_output


HEADER_FIELDS = (
    "发票代码",
    "发票号码",
    "开票日期",
    "购买方名称",
    "购买方税号",
    "购买方地址电话",
    "购买方开户行及账号",
    "销售方名称",
    "销售方税号",
    "销售方地址电话",
    "销售方开户行及账号",
    "合计金额（不含税）",
    "合计税额",
    "价税合计（小写）",
    "价税合计（大写）",
    "备注",
)
ITEM_FIELDS = ("项目名称", "规格型号", "单位", "数量", "单价", "金额", "税率", "税额")
VALIDATION_FIELDS = (
    "发票号码",
    "明细行号",
    "校验项",
    "是否异常",
    "异常字段",
    "实际值",
    "应为",
    "差额",
    "说明",
)
MONEY_TOLERANCE = Decimal("0.02")


class ScannedPdfUnsupportedError(RuntimeError):
    def __init__(self, pages):
        page_text = "、".join(map(str, pages))
        super().__init__(f"第 {page_text} 页是扫描图片，当前版本仅支持文本型 PDF 发票。")


@dataclass(frozen=True)
class TextBlock:
    text: str
    page: int
    x0: float = 0
    top: float = 0
    x1: float = 0


@dataclass
class InvoiceItem:
    project_name: str = ""
    specification: str = ""
    unit: str = ""
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    tax_rate_text: str = ""


@dataclass(frozen=True)
class ValidationRecord:
    invoice_number: str
    item_row: str
    check: str
    abnormal: bool
    abnormal_fields: str = ""
    actual: Optional[Decimal] = None
    expected: Optional[Decimal] = None
    difference: Optional[Decimal] = None
    note: str = ""


@dataclass
class InvoiceData:
    header: dict = field(default_factory=lambda: {name: "" for name in HEADER_FIELDS})
    items: list = field(default_factory=list)
    validations: list = field(default_factory=list)


@dataclass(frozen=True)
class PdfInvoiceResult:
    output_file: str
    item_count: int
    abnormal_count: int
    source_file: str = ""
    invoice_number: str = ""
    invoice_date: str = ""
    buyer_name: str = ""
    seller_name: str = ""
    seller_tax_id: str = ""
    amount: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    total_amount: Optional[Decimal] = None


@dataclass(frozen=True)
class InvoiceLedgerResult:
    output_file: str
    log_file: str
    log_error: str = ""


def _clean_text(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\u200b", "").replace("\ufeff", "")
    if "%" in text:
        text = re.sub(r"(\d)\s*%", r"\1%", text)
    return " ".join(text.split()).strip(" |丨")


def _compact(value):
    return re.sub(r"[\s:：()（）]", "", _clean_text(value))


def _group_lines(blocks, tolerance=5):
    grouped = []
    pages = {}
    for block in blocks:
        if _clean_text(block.text):
            pages.setdefault(block.page, []).append(block)
    for page in sorted(pages):
        page_blocks = sorted(pages[page], key=lambda block: (block.top, block.x0))
        page_lines = []
        for block in page_blocks:
            if not page_lines or abs(page_lines[-1][0].top - block.top) > tolerance:
                page_lines.append([block])
            else:
                page_lines[-1].append(block)
        grouped.extend(sorted(line, key=lambda block: block.x0) for line in page_lines)
    return grouped


def _line_text(line):
    return " ".join(filter(None, (_clean_text(block.text) for block in line)))


def _extract_first(patterns, text):
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _clean_text(match.group(1))
    return ""


def _extract_party(lines, start_label, end_labels):
    start = next(
        (index for index, line in enumerate(lines) if start_label in _compact(line)),
        None,
    )
    if start is None:
        return {}
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if any(label in _compact(lines[index]) for label in end_labels)
        ),
        len(lines),
    )
    result = {"名称": "", "税号": "", "地址电话": "", "开户行及账号": ""}
    label_pattern = re.compile(
        r"(纳税人识别号|统一社会信用代码|"
        r"开户行及账号|开户银行及账号|银行账号|"
        r"地址\s*[、,]?\s*电话|税号|名称)\s*[:：]?",
        re.IGNORECASE,
    )

    def field_name(label):
        compact = re.sub(r"[\s、,]", "", label)
        if compact == "名称":
            return "名称"
        if compact in ("纳税人识别号", "统一社会信用代码", "税号"):
            return "税号"
        if compact == "地址电话":
            return "地址电话"
        return "开户行及账号"

    current_field = None
    for line in lines[start + 1 : end]:
        matches = list(label_pattern.finditer(line))
        if not matches:
            if current_field:
                result[current_field] += _clean_text(line)
            continue
        for index, match in enumerate(matches):
            current_field = field_name(match.group(1))
            value_end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
            result[current_field] += _clean_text(line[match.end() : value_end])
    return result


def _parallel_parties(grouped):
    """Separate horizontal party panels before reading any of their fields."""
    headings = {}
    suffixes = ("名称", "税号", "地址电话", "开户行及账号")
    unidentified = {"购买方名称", "销售方名称", "购买方税号", "销售方税号"}
    content = []
    for line in grouped:
        if line[0].page != grouped[0][0].page:
            break
        text = _compact(_line_text(line))
        if any(word in text for word in ("项目名称", "货物或应税劳务", "价税合计")):
            break
        for block in line:
            if "购买方" not in block.text and "销售方" not in block.text:
                continue
            if "购买方" in block.text and "销售方" in block.text:
                return {}, unidentified
            match = re.match(r"(购买方|销售方)(?:信息|名称|税号|[:：\s]|$)", block.text)
            if match:
                headings.setdefault(match[1], block)
        if headings:
            content.append(line)
    if len(headings) != 2:
        return None
    buyer, seller = headings["购买方"], headings["销售方"]
    paired_labels = next(([b.x0 for b in line if b.text.startswith("名称")]
                          for line in content if sum(b.text.startswith("名称") for b in line) == 2), [])
    if abs(buyer.top - seller.top) > 12 and not paired_labels:
        return None  # Stacked buyer and seller sections.
    if abs(buyer.x0 - seller.x0) < 10:
        return {}, unidentified
    roles = sorted(headings, key=lambda role: headings[role].x0)
    sections = {}
    ambiguous = set()
    # If the titles are centered, paired field labels give the true start
    # of the right column. Do not infer a division from page width.
    boundary = headings[roles[1]].x0
    if paired_labels:
        boundary = min(boundary, paired_labels[1])
    columns = {r: [] for r in roles}
    for line in content:
        if any("发票号码" in b.text or "开票日期" in b.text or "发票代码" in b.text for b in line):
            continue
        parts = {r: [] for r in roles}
        for b in line:
            role = roles[0] if b.x0 < boundary else roles[1]
            value = b.text
            for caption, block in headings.items():
                if b is block:
                    role = caption
                    value = value.partition(caption)[2].removeprefix("信息").lstrip(" :：")
            if value:
                if b.x0 < boundary < b.x1 - 1:
                    ambiguous.update(role + x for x in suffixes)
                parts[role].append(value)
        for role in roles:
            if parts[role]:
                columns[role].append(" ".join(parts[role]))
    for role in roles:
        party = _extract_party([role, *columns[role]], role, ())
        for key in suffixes:
            field_name = role + key
            sections[field_name] = "" if field_name in ambiguous else party.get(key, "")
        if not sections[role + "名称"]:
            ambiguous.add(role + "名称")
    return sections, ambiguous


def _decimal_tokens(text):
    # Keep a malformed run intact so _to_decimal rejects the whole field.
    return re.findall(r"[-+]?[.,]*\d[\d,.]*%?", _clean_text(text))


def _to_decimal(value, percent=False):
    if value in (None, ""):
        return None
    text = _clean_text(value).replace("¥", "").replace("￥", "")
    is_percent = text.endswith("%")
    text = text.rstrip("%").strip()
    if "," in text:
        if not re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
            return None
        text = text.replace(",", "")
    # Multiple decimal points can be overlapping PDF text, not a number to repair.
    # Keep the field missing so validation reports it instead of inventing money.
    if text.count(".") > 1:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    if percent or is_percent:
        number /= 100
    return number


def _malformed_numeric(token):
    return bool(token and ("," in token or token.count(".") > 1)
                and re.fullmatch(r"[¥￥]?[-+]?[\d.,]+%?", token)
                and _to_decimal(token) is None)


def _record_amount(report, field_name, raw, row=""):
    if report and _malformed_numeric(raw):
        report("数字格式", field_name, f"{field_name}的票面原文为“{raw}”，数字格式异常，未参与计算。", row)


_TEXT_TAX_RATES = {"免税", "不征税"}


def _build_item(text_parts, numeric_parts, rate_token, report=None, row=""):
    numbers = [_to_decimal(token) for token in numeric_parts]
    rate = _to_decimal(rate_token, percent=True) if rate_token else None
    if rate is not None:
        if len(numbers) < 4:
            return None
        quantity, unit_price, amount = numbers[-4:-1]
        tax_amount = numbers[-1]
    elif len(numbers) >= 4:
        quantity, unit_price, amount, tax_amount = numbers[-4:]
    elif len(numbers) >= 3:
        quantity, unit_price, amount = numbers[-3:]
        tax_amount = None
    else:
        return None

    text_parts = [_clean_text(part) for part in text_parts if _clean_text(part)]
    item = InvoiceItem(
        project_name=text_parts[0] if text_parts else "",
        specification=text_parts[1] if len(text_parts) > 1 else "",
        unit=" ".join(text_parts[2:]) if len(text_parts) > 2 else "",
        quantity=quantity,
        unit_price=unit_price,
        amount=amount,
        tax_rate=rate,
        tax_rate_text=rate_token if rate_token in _TEXT_TAX_RATES else "",
        tax_amount=tax_amount,
    )
    keys = ("数量", "单价", "金额", "税额") if len(numbers) >= 4 else ("数量", "单价", "金额")
    for key, token in zip(keys, numeric_parts[-len(keys):]):
        _record_amount(report, key, token, row)
    _record_amount(report, "税率", rate_token, row)
    return item


def _extract_items(lines, report=None, offset=0):
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if ("项目名称" in _compact(line) or "货物或应税劳务" in _compact(line))
            and any(label in _compact(line) for label in ("金额", "数量", "税额"))
        ),
        None,
    )
    if start is None:
        return []

    content = []
    for line in lines[start + 1 :]:
        compact = _compact(line)
        if "价税合计" in compact or compact.startswith("合计"):
            break
        if line.strip():
            content.append(line)

    items = []
    text_parts = []
    numeric_parts = []
    rate_token = ""

    def finish():
        nonlocal text_parts, numeric_parts, rate_token
        item = _build_item(text_parts, numeric_parts, rate_token, report, str(offset + len(items) + 1))
        if item:
            items.append(item)
        text_parts, numeric_parts, rate_token = [], [], ""

    for line in content:
        tokens = _clean_text(line).split()
        rates = [token for token in tokens if token in _TEXT_TAX_RATES or (token.endswith("%") and (_to_decimal(token, True) is not None or _malformed_numeric(token)))]
        numbers = [
            token
            for token in tokens
            if not token.endswith("%") and (_to_decimal(token) is not None or _malformed_numeric(token))
        ]
        texts = [token for token in tokens if token not in rates and token not in numbers and token != "***"]

        if texts and numeric_parts:
            finish()
        text_parts.extend(texts)
        numeric_parts.extend(numbers)
        if rates:
            rate_token = rates[-1]
    finish()
    return items


_ITEM_HEADINGS = {name: name for name in ITEM_FIELDS}
_ITEM_HEADINGS.update({"税率/征收率": "税率", "税率或征收率": "税率",
                       "货物或应税劳务、服务名称": "项目名称", "货物或应税劳务名称": "项目名称"})
_LEGACY_ITEM_LAYOUT = ((119, 190, 245, 310, 385, 450, 530), ITEM_FIELDS)


def _item_layout(header, rules):
    """Read distinct column titles, joining titles printed as separate characters."""
    anchors = []
    i = 0
    while i < len(header):
        for end in range(min(len(header), i + 4), i, -1):
            title = _compact("".join(b.text for b in header[i:end]))
            if title in _ITEM_HEADINGS:
                anchors.append((_ITEM_HEADINGS[title], header[i].x0, header[end - 1].x1))
                i = end
                break
        else:
            # A flattened header has no individual column coordinates.
            return _LEGACY_ITEM_LAYOUT
    fields = tuple(a[0] for a in anchors)
    if not {"项目名称", "金额", "税额"}.issubset(fields) or len(set(fields)) != len(fields):
        return _LEGACY_ITEM_LAYOUT
    y = min(b.top for b in header)
    dividers = [x for x, top, bottom in rules if top <= y + 2 and bottom > y + 5]
    bounds = []
    for (_, _, right), (_, left, _) in zip(anchors, anchors[1:]):
        if left < right:
            return _LEGACY_ITEM_LAYOUT
        middle = (right + left) / 2
        lines = [x for x in dividers if right <= x <= left]
        bounds.append(min(lines, key=lambda x: abs(x - middle)) if lines else middle)
    return bounds, fields


def _item_cells(line, layout):
    bounds, fields = layout
    cells = {}
    for block in line:
        start = fields[bisect_right(bounds, block.x0)]
        # A long, left-aligned name or model can extend into the next column.
        field = start
        if start not in ("项目名称", "规格型号"):
            field = fields[bisect_right(bounds, (block.x0 + block.x1) / 2)]
        cells[field] = cells.get(field, "") + _clean_text(block.text)
    return cells


def _continuation_lines(lines, layout, page, report):
    """Use the previous table only for rows corroborated by its numeric columns."""
    selected = []
    doubtful = False
    for line in lines:
        text = _line_text(line)
        compact = _compact(text)
        if compact.startswith(("小计", "合计", "价税合计", "备注", "开票人", "收款人", "复核")):
            break
        if re.fullmatch(r"第?\d+页(?:共\d+页)?|\d+/\d+", compact):
            continue
        if any(label in compact for label in ("发票号码", "发票代码", "开票日期", "纳税人识别号")):
            continue
        tokens = text.split()
        numeric = sum(bool(re.fullmatch(r"[¥￥]?[+-]?[\d,.]+%?", token)) for token in tokens)
        has_rate = "%" in text or any(t in _TEXT_TAX_RATES for t in tokens)
        cells = _item_cells(line, layout) if layout is not None else {}
        if numeric < 2 and not has_rate:
            if numeric and cells.get("金额") and (cells.get("项目名称") or cells.get("规格型号")):
                doubtful = True
            elif selected and cells and cells.keys() <= {"项目名称", "规格型号"}:
                selected.append(line)
            continue
        amount = cells.get("金额", "")
        rate = cells.get("税率", "")
        tax = cells.get("税额", "")
        rate_matches = (rate.endswith("%") and _to_decimal(rate, True) is not None) or rate in _TEXT_TAX_RATES
        tax_matches = _to_decimal(tax) is not None or tax == "***" or _malformed_numeric(tax)
        if (re.fullmatch(r"[¥￥]?[+-]?[\d,.]+", amount)
                and tax_matches and (rate_matches or (layout and "税率" not in layout[1]))):
            selected.append(line)
        else:
            doubtful = True
    if doubtful and report:
        report("续页明细", "明细", f"第 {page} 页有疑似明细无法与前页列位置对应，请逐行核对原票。")
    return selected


def _positioned_items(blocks, column_rules=None, report=None):
    items = []
    grouped = _group_lines(blocks, tolerance=3)
    by_page = {}
    for line in grouped:
        by_page.setdefault(line[0].page, []).append(line)
    previous_layout = None
    for page, page_lines in by_page.items():
        header_index = None
        for index, line in enumerate(page_lines):
            title = _compact(_line_text(line))
            if "税额" in title and ("项目名称" in title or "货物或应税劳务" in title):
                header_index = index
                break
        if header_index is None:
            flat = _extract_items([_line_text(line) for line in page_lines], report, len(items))
            if flat or not items:
                items.extend(flat)
                previous_layout = None
                continue
            layout = previous_layout
            content = _continuation_lines(page_lines, layout, page, report)
            if not content:
                continue
            subtotal_tops = []
        else:
            layout = _item_layout(page_lines[header_index], (column_rules or {}).get(page, ()))
            previous_layout = layout if layout is not _LEGACY_ITEM_LAYOUT else None
            subtotal_tops = [
                min(block.top for block in line)
                for line in page_lines
                if _compact(_line_text(line)).startswith("小计")
            ]
            content = []
            for line in page_lines[header_index + 1:]:
                compact = _compact(_line_text(line))
                if compact.startswith(("小计", "合计", "价税合计", "备注")):
                    break
                content.append(line)

        rows = [_item_cells(line, layout) for line in content]
        numeric_indexes = []
        for index, line in enumerate(content):
            line_top = min(block.top for block in line)
            if any(abs(line_top - top) <= 10 for top in subtotal_tops):
                continue
            amount_text = rows[index].get("金额", "")
            # A numeric amount with multiple decimal points still identifies
            # an item row. Leave its amount blank for the existing checks.
            if _to_decimal(amount_text) is not None or _malformed_numeric(amount_text):
                numeric_indexes.append(index)
        if not numeric_indexes:
            if header_index is not None:
                items.extend(_extract_items([_line_text(line) for line in page_lines[header_index:]], report, len(items)))
            continue

        leading_rows = rows[:numeric_indexes[0]]
        if items:
            # A category marker starts the next item. Text before it continues
            # the previous page's item, in the original name/model column.
            for index, row in enumerate(leading_rows):
                name = row.get("项目名称", "")
                marker = re.search(r"\*(?=[\u3400-\u9fff]{1,20}\*)", name)
                if marker:
                    items[-1].project_name += name[:marker.start()]
                    leading_rows = [{**row, "项目名称": name[marker.start():]}, *leading_rows[index + 1:]]
                    break
                items[-1].project_name += name
                items[-1].specification += row.get("规格型号", "")
            else:
                leading_rows = []

        for position, row_index in enumerate(numeric_indexes):
            end = numeric_indexes[position + 1] if position + 1 < len(numeric_indexes) else len(rows)
            row_lines = rows[row_index:end]
            first = row_lines[0]
            if position == 0 and leading_rows:
                row_lines = leading_rows + row_lines
            for key in ("数量", "单价", "金额", "税额", "税率"):
                raw = first.get(key, "")
                if "," in raw or raw.count(".") > 1:
                    _record_amount(report, key, raw, str(len(items) + 1))
            rate_text = first.get("税率", "")
            items.append(InvoiceItem(
                project_name="".join(row.get("项目名称", "") for row in row_lines),
                specification="".join(row.get("规格型号", "") for row in row_lines),
                unit=first.get("单位", ""),
                quantity=_to_decimal(first.get("数量")),
                unit_price=_to_decimal(first.get("单价")),
                amount=_to_decimal(first.get("金额")),
                tax_rate=_to_decimal(rate_text, percent=True),
                tax_rate_text=rate_text if rate_text in _TEXT_TAX_RATES else "",
                tax_amount=_to_decimal(first.get("税额")),
            ))
    return items


def _parties_from_blocks(blocks):
    first_page = min((block.page for block in blocks), default=1)
    page_blocks = [block for block in blocks if block.page == first_page]
    if not page_blocks:
        return {}, {}
    page_width = max((block.x1 for block in page_blocks), default=600)
    if page_width < 100:
        return {}, {}

    def extract(minimum, maximum):
        result = {}
        for block in page_blocks:
            if not minimum <= block.x0 < maximum:
                continue
            compact = _compact(block.text).replace("、", "").replace("/", "")
            field = None
            if compact == "名称":
                field = "名称"
            elif "纳税人识别号" in compact or "统一社会信用代码" in compact:
                field = "税号"
            elif "地址电话" in compact:
                field = "地址电话"
            elif "开户行及账号" in compact or "开户银行及账号" in compact:
                field = "开户行及账号"
            if not field:
                continue
            values = [
                candidate
                for candidate in page_blocks
                if candidate is not block
                and abs(candidate.top - block.top) <= 4
                and candidate.x0 >= block.x1 - 6
                and candidate.x0 < maximum
            ]
            values.sort(key=lambda candidate: candidate.x0)
            if field in ("名称", "税号") and values:
                adjacent = [values[0]]
                for candidate in values[1:]:
                    if candidate.x0 - adjacent[-1].x1 > 10:
                        break
                    adjacent.append(candidate)
                values = adjacent
            value = "".join(
                _clean_text(candidate.text)
                for candidate in values
            )
            if field == "税号":
                value = re.sub(r"[^0-9A-Z]", "", value.upper())
            if value:
                result[field] = value
        return result

    midpoint = page_width / 2
    return extract(20, midpoint), extract(midpoint, page_width + 1)


_SIGNATURE = re.compile(r"^(?:开票人|收款人|复核人?)\s*:")


def _boxed_remark(page, words):
    """Return text in the ruled value cell, '' for an empty cell, or None for no box."""
    labels = [word for word in words
              if "备" in word["text"] and _compact(word["text"]) in ("备", "备注")]
    if not labels:
        return None
    horizontal = [edge for edge in page.edges if edge["orientation"] == "h"]
    vertical = [edge for edge in page.edges if edge["orientation"] == "v"]
    # Some PDF producers draw the adjoining ends of two rules slightly apart.
    # This tolerance joins ink strokes only; it never enlarges the text region.
    join = 1.5
    for label in labels:
        x = (label["x0"] + label["x1"]) / 2
        y = (label["top"] + label["bottom"]) / 2
        crossing = [e["top"] for e in horizontal if e["x0"] <= x <= e["x1"]]
        top = max((v for v in crossing if v < y), default=None)
        bottom = min((v for v in crossing if v > y), default=None)
        if top is None or bottom is None:
            continue
        if _compact(label["text"]) == "备" and not any(
            word["text"] == "注" and word["x0"] <= x <= word["x1"]
            and y < (word["top"] + word["bottom"]) / 2 < bottom for word in words
        ):
            continue
        sides = sorted({e["x0"] for e in vertical
                        if e["top"] <= top + join and e["bottom"] >= bottom - join})
        left = max((v for v in sides if v < x), default=None)
        right_sides = [v for v in sides if v > x]
        if left is None or not right_sides:
            continue
        divider = right_sides[0]
        right = next((v for v in right_sides if v > divider + join), None)
        if right is None:
            continue
        # Both the label and its neighbour must be closed at the top and bottom.
        if not all(any(abs(e["top"] - height) <= join and e["x0"] <= start + join
                       and e["x1"] >= end - join for e in horizontal)
                   for height in (top, bottom) for start, end in ((left, divider), (divider, right))):
            continue
        content = [TextBlock(w["text"], 1, w["x0"], w["top"], w["x1"]) for w in words
                   if divider < (w["x0"] + w["x1"]) / 2 < right
                   and top < (w["top"] + w["bottom"]) / 2 < bottom]
        return "\n".join(_line_text(line) for line in _group_lines(content))
    return None


def _positioned_remark(blocks, grouped):
    """Read a vertical remark label's box, including text above the label.

    The gross-total row and signature row bound the box vertically. The label
    bounds it on the left, so seller fields beside an old-style box stay out.
    """
    for first in blocks:
        if "备" not in first.text or _compact(first.text) != "备":
            continue
        second = next((block for block in blocks if block.page == first.page
                       and _compact(block.text) == "注" and abs(block.x0 - first.x0) <= 1
                       and 0 < block.top - first.top <= 80), None)
        if second is None:
            continue
        rows = [line for line in grouped if line[0].page == first.page]
        total_row = next((i for i in reversed(range(len(rows)))
                          if rows[i][0].top < first.top and "价税合计" in _compact(_line_text(rows[i]))), None)
        signature_row = next((i for i, line in enumerate(rows)
                              if line[0].top > second.top and _SIGNATURE.match(_line_text(line))), None)
        if total_row is None or signature_row is None:
            return None
        left = max(first.x1, second.x1)
        contents = [_line_text([b for b in line if b.x0 > left])
                    for line in rows[total_row + 1:signature_row]]
        value = "\n".join(filter(None, contents))
        if value and _SIGNATURE.fullmatch(_line_text(rows[signature_row])):
            # A detached name cannot be distinguished from a note without a box.
            return None
        return value

    # Flat text/OCR inputs may expose a horizontal field instead of a ruled box.
    for index, line in enumerate(grouped):
        if not any("备注" in block.text for block in line):
            continue
        match = re.search(r"(?:^|\s)备注\s*:?\s*(.*)$", _line_text(line))
        if match:
            value = match.group(1)
            if value:
                return value
            if index + 1 < len(grouped) and grouped[index + 1][0].page == line[0].page:
                following = _line_text(grouped[index + 1])
                if not _SIGNATURE.match(following) and not following.startswith("销售方"):
                    return following
    return ""


def _invoice_remark(blocks, grouped, boxed):
    if isinstance(boxed, str):
        return boxed, []
    if grouped and grouped[0][0].page == grouped[-1][0].page:
        page = grouped[0][0].page
        value = (boxed or {}).get(page)
        if value is None:
            value = _positioned_remark(blocks, grouped)
        return value or "", [page] if value is None else []
    pages = {}
    for line in grouped:
        pages.setdefault(line[0].page, []).append(line)
    entries = []
    unclear = []
    for page, lines in pages.items():
        value = (boxed or {}).get(page)
        if value is None:
            value = _positioned_remark([b for line in lines for b in line], lines)
        if value is None:
            unclear.append(page)
        elif value:
            entries.append((page, value))
    if len({value for _, value in entries}) <= 1:
        return (entries[0][1] if entries else ""), unclear
    return "\n".join(f"第 {page} 页：{value}" for page, value in entries), unclear


_DATE_PATTERN = re.compile(r"(?:([0-9]{4})([-/.])([0-9]{1,2})\2([0-9]{1,2})"
                           r"|([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日?"
                           r"|([0-9]{4})([0-9]{2})([0-9]{2}))")


def _excel_date(value):
    match = _DATE_PATTERN.fullmatch(re.sub(r"\s+", "", value))
    if not match:
        return None
    if match[1]:
        parts = match.group(1, 3, 4)
    elif match[5]:
        parts = match.group(5, 6, 7)
    else:
        parts = match.group(8, 9, 10)
    try:
        return datetime(*map(int, parts)).date()
    except ValueError:
        return None


def _printed_date(text):
    match = re.search(r"开票日期[^\S\n]*:?[^\S\n]*([^\n]*)", text)
    if not match:
        return ""
    value = match[1].strip()
    if not value:
        following = text[match.end():].lstrip("\n").split("\n", 1)[0]
        value = following if re.match(r"\d{4}[-/.年\d]", following) else ""
    # Stop at another heading on the same line, never borrow its contents.
    value = re.split(r"(?:发票(?:号码|代码)|购买方|销售方|校验码|机器编号)\s*:?", value)[0].strip()
    return value


def _extract_header(lines, parallel_parties=None, report=None):
    header = {name: "" for name in HEADER_FIELDS}
    text = "\n".join(lines)
    header["开票日期"] = _printed_date(text)
    invalid = {}

    def money(key, raw):
        header[key] = _to_decimal(raw)
        if _malformed_numeric(raw):
            invalid[key] = raw
        else:
            invalid.pop(key, None)

    if parallel_parties is not None:
        header.update(parallel_parties[0])
    else:
        buyer = _extract_party(lines, "购买方", ("项目名称", "销售方"))
        seller = _extract_party(
            lines,
            "销售方",
            ("项目名称", "收款人", "复核", "开票人"),
        )
        for prefix, party in (("购买方", buyer), ("销售方", seller)):
            header[f"{prefix}名称"] = party.get("名称", "")
            header[f"{prefix}税号"] = party.get("税号", "")
            header[f"{prefix}地址电话"] = party.get("地址电话", "")
            header[f"{prefix}开户行及账号"] = party.get("开户行及账号", "")

    for line in lines:
        compact = _compact(line)
        if not (compact.startswith("合计") or "价税合计" in compact):
            continue
        numbers = _decimal_tokens(line)
        if compact.startswith("合计税额"):
            money("合计税额", numbers[0] if numbers else "")
            continue
        if compact.startswith("合计") and "价税合计" not in compact:
            if numbers:
                money("合计金额（不含税）", numbers[0])
            if len(numbers) > 1:
                money("合计税额", numbers[-1])
        if "价税合计" in compact:
            if numbers:
                money("价税合计（小写）", numbers[-1])
            large = re.search(r"大写[\s:：)）]*([^\d￥¥(（]+)", line)
            if large:
                header["价税合计（大写）"] = _clean_text(large.group(1))

    if header["合计金额（不含税）"] in ("", None) and "合计金额（不含税）" not in invalid:
        value = _extract_first(
            (r"合计金额(?:（不含税）|\(不含税\))?[^\S\n]*[:：]?[^\S\n]*[￥¥]?[^\S\n]*([-+]?\d[\d,.]*)",),
            text,
        )
        money("合计金额（不含税）", value)
    if header["合计税额"] in ("", None) and "合计税额" not in invalid:
        value = _extract_first((r"合计税额[^\S\n]*[:：]?[^\S\n]*[￥¥]?[^\S\n]*([-+]?\d[\d,.]*)",), text)
        money("合计税额", value)
    if header["价税合计（小写）"] in ("", None) and "价税合计（小写）" not in invalid:
        value = _extract_first(
            (r"价税合计(?:（小写）|\(小写\))?[^\S\n]*[:：]?[^\S\n]*[￥¥]?[^\S\n]*([-+]?\d[\d,.]*)",),
            text,
        )
        money("价税合计（小写）", value)

    for key, raw in invalid.items():
        _record_amount(report, key, raw)
    return header


def validate_invoice(invoice):
    records = []
    invoice_number = invoice.header.get("发票号码", "")

    def add(item_row, check, fields, actual, expected, note=""):
        missing = [field for field, value in fields if value is None]
        if missing:
            records.append(
                ValidationRecord(
                    invoice_number,
                    item_row,
                    check,
                    True,
                    "、".join(missing),
                    note="校验所需字段缺失",
                )
            )
            return
        difference = abs(actual - expected)
        records.append(
            ValidationRecord(
                invoice_number,
                item_row,
                check,
                difference > MONEY_TOLERANCE,
                "、".join(field for field, _ in fields) if difference > MONEY_TOLERANCE else "",
                actual,
                expected,
                difference,
                note,
            )
        )

    printed_date = invoice.header.get("开票日期", "")
    if not printed_date or _excel_date(printed_date) is None:
        note = f"开票日期的票面原文为“{printed_date}”，无法识别为有效日期。" if printed_date else "未识别到开票日期，请对照原票核对。"
        records.append(ValidationRecord(invoice_number, "", "开票日期", True, "开票日期", note=note))
    for index, item in enumerate(invoice.items, 1):
        if item.amount is not None and item.amount < 0 and (
            item.quantity is None or item.unit_price is None
        ):
            records.append(
                ValidationRecord(
                    invoice_number,
                    str(index),
                    "数量 × 单价 ≈ 金额",
                    False,
                    note="折扣/调整行，数量与单价不适用",
                )
            )
        else:
            add(
                str(index),
                "数量 × 单价 ≈ 金额",
                (("数量", item.quantity), ("单价", item.unit_price), ("金额", item.amount)),
                item.quantity * item.unit_price if None not in (item.quantity, item.unit_price) else Decimal(0),
                item.amount or Decimal(0),
            )
        if item.tax_rate_text:
            records.append(ValidationRecord(
                invoice_number, str(index), "金额 × 税率 ≈ 税额", True, "税率",
                note=f"票面税率为“{item.tax_rate_text}”，无法按数值税率复算，请核对原票。",
            ))
            continue
        add(
            str(index),
            "金额 × 税率 ≈ 税额",
            (("金额", item.amount), ("税率", item.tax_rate), ("税额", item.tax_amount)),
            item.amount * item.tax_rate if None not in (item.amount, item.tax_rate) else Decimal(0),
            item.tax_amount or Decimal(0),
        )

    amount = invoice.header.get("合计金额（不含税）")
    tax = invoice.header.get("合计税额")
    gross = invoice.header.get("价税合计（小写）")
    add(
        "",
        "金额 + 税额 ≈ 价税合计",
        (("合计金额（不含税）", amount), ("合计税额", tax), ("价税合计（小写）", gross)),
        amount + tax if None not in (amount, tax) else Decimal(0),
        gross or Decimal(0),
    )

    detail_amount = sum((item.amount or Decimal(0) for item in invoice.items), Decimal(0))
    detail_tax = sum((item.tax_amount or Decimal(0) for item in invoice.items), Decimal(0))
    add(
        "",
        "明细金额合计 ≈ 发票合计金额",
        (("明细金额", detail_amount), ("合计金额（不含税）", amount)),
        detail_amount,
        amount or Decimal(0),
    )
    add(
        "",
        "明细税额合计 ≈ 发票合计税额",
        (("明细税额", detail_tax), ("合计税额", tax)),
        detail_tax,
        tax or Decimal(0),
    )
    invoice.validations = records
    return records


_INVOICE_ID = re.compile(r"(?<![\w])发票(代码|号码)\s*[:：]?\s*([0-9A-Z][0-9A-Z ]{5,29})", re.I)


def _document_identity(grouped, lines):
    by_page = {}
    for row, text in zip(grouped, lines):
        by_page.setdefault(row[0].page, []).append(text)
    identities = set()
    all_codes = set()
    number = ""
    for page_lines in by_page.values():
        codes, numbers = set(), set()
        for field, value in _INVOICE_ID.findall("\n".join(page_lines)):
            value = value.replace(" ", "").upper()
            if field == "代码" and len(value) >= 8:
                codes.add(value)
            elif field == "号码":
                numbers.add(value)
        all_codes.update(codes)
        if numbers:
            number = next(iter(numbers))
            identities.update((next(iter(codes), ""), n) for n in numbers)
        if len(all_codes) > 1 or len(identities) > 1:
            raise ValueError("检测到多张发票，请拆分为每个 PDF 一张发票后再处理。")
    return next(iter(all_codes), ""), number


def parse_invoice_blocks(blocks, *, boxed_remark=None, column_rules=None):
    grouped = _group_lines(blocks)
    lines = [_line_text(line) for line in grouped]
    code, number = _document_identity(grouped, lines)
    issues = []

    def report(check, fields, note, row=""):
        issues.append(ValidationRecord(number, row, check, True, fields, note=note))

    parallel = _parallel_parties(grouped) if any("购买方" in t for t in lines) and any("销售方" in t for t in lines) else None
    header = _extract_header(lines, parallel, report)
    header["发票代码"], header["发票号码"] = code, number
    header["备注"], unclear_remarks = _invoice_remark(blocks, grouped, boxed_remark)
    if parallel is None:
        buyer, seller = _parties_from_blocks(blocks)
        for prefix, party in (("购买方", buyer), ("销售方", seller)):
            for suffix in ("名称", "税号", "地址电话", "开户行及账号"):
                if party.get(suffix) and not header[f"{prefix}{suffix}"]:
                    header[f"{prefix}{suffix}"] = party[suffix]
    items = _positioned_items(blocks, column_rules, report)
    invoice = InvoiceData(header=header, items=items)
    if not invoice.items:
        raise ValueError("未能识别包含“金额”的发票明细，未生成 Excel。")
    validate_invoice(invoice)
    invoice.validations.extend(issues)
    if parallel and parallel[1]:
        invoice.validations.append(ValidationRecord(number, "", "购销方识别", True, "、".join(sorted(parallel[1])),
                                                    note="左右栏归属不能确定，请对照原票核对所列字段。"))
    for page in unclear_remarks:
        invoice.validations.append(ValidationRecord(
            invoice_number=header["发票号码"], item_row="", check="备注识别", abnormal=True,
            abnormal_fields="备注", note=f"第 {page} 页无法确定备注与签名栏的边界，该页备注已留空，请对照原票核对。",
        ))
    return invoice


def _deduplicated_text_page(page):
    """Ignore exact overprints on this page, preserving real repeated text/rows.

    Compare glyphs, not words: duplicate text can have different word boundaries.
    Exact geometry plus font/size/orientation avoids merging nearby characters.
    One pass avoids quadratic character searches on long invoice pages.
    """
    seen = set()
    duplicate_ids = set()
    glyph_key = itemgetter("text", "fontname", "size", "upright", "x0", "x1", "top", "bottom")
    for char in page.chars:
        try:
            key = glyph_key(char)
        except KeyError:
            continue  # Incomplete geometry or font information cannot prove an overprint.
        if key in seen:
            duplicate_ids.add(id(char))
        else:
            seen.add(key)
    if not duplicate_ids:
        return page
    return page.filter(lambda obj: id(obj) not in duplicate_ids)


def _pdf_text_blocks(pdf_file, progress_callback=None, *, column_rules=None):
    from utils.pdf_helper import open_pdf

    if progress_callback:
        progress_callback(0, 0, "正在读取 PDF 文件结构…")

    blocks = []
    scanned_pages = []
    page_remarks = {}
    with open_pdf(pdf_file) as document:
        total = len(document.pages)
        if total == 0:
            raise ValueError("PDF 中没有可处理页面。")
        if total > 100:
            raise ValueError("PDF 超过 100 页，请拆分后再处理。")
        if progress_callback:
            progress_callback(0, total, f"已读取 PDF，共 {total} 页")
        for page_number, page in enumerate(document.pages, 1):
            text_page = _deduplicated_text_page(page)
            words = text_page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
            visible_text = "".join(str(word.get("text", "")) for word in words)
            page_area = max(float(page.width) * float(page.height), 1)
            has_page_image = any(
                float(image.get("width", 0)) * float(image.get("height", 0))
                >= page_area * 0.25
                for image in page.images
            )
            if len(re.sub(r"\s", "", visible_text)) < 20 and has_page_image:
                scanned_pages.append(page_number)
            else:
                if column_rules is not None and words:
                    column_rules[page_number] = [(e["x0"], e["top"], e["bottom"]) for e in page.edges
                                                 if e["orientation"] == "v"]
                if words:
                    page_remarks[page_number] = _boxed_remark(page, words)
                blocks.extend(
                    TextBlock(
                        text=word.get("text", ""),
                        page=page_number,
                        x0=float(word.get("x0", 0)),
                        top=float(word.get("top", 0)),
                        x1=float(word.get("x1", 0)),
                    )
                    for word in words
                )
            if progress_callback:
                progress_callback(page_number, total, f"正在读取第 {page_number} 页")
    return blocks, scanned_pages, page_remarks.get(1) if total == 1 else page_remarks


def extract_invoice(pdf_file, progress_callback=None, prefer_fast=None):
    if isinstance(pdf_file, (str, os.PathLike)):
        pdf_file = os.path.abspath(pdf_file)
        if Path(pdf_file).suffix.lower() != ".pdf":
            raise ValueError("只支持 PDF 文件。")
        if not os.path.isfile(pdf_file):
            raise FileNotFoundError("PDF 文件不存在。")

    # ``prefer_fast`` is kept only for compatibility with older callers.  A
    # flattened text stream loses the left/right columns used by Chinese VAT
    # invoices, so every platform now reads positioned text from the start.
    column_rules = {}
    blocks, scanned_pages, boxed_remark = _pdf_text_blocks(pdf_file, progress_callback, column_rules=column_rules)
    if scanned_pages:
        raise ScannedPdfUnsupportedError(scanned_pages)
    return parse_invoice_blocks(blocks, boxed_remark=boxed_remark, column_rules=column_rules)


def _excel_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("=", "+", "-", "@")):
            return "'" + text
        return text
    return value


def _date_value(value):
    if not value:
        return ""
    return _excel_date(str(value)) or _excel_value(value)


def _style_sheet(sheet, widths):
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.row_dimensions[1].height = 26
    title_fill = PatternFill("solid", fgColor="17365D")
    title_font = Font(color="FFFFFF", bold=True)
    title_alignment = Alignment(horizontal="center", vertical="center")
    for cell in sheet[1]:
        cell.fill = title_fill
        cell.font = title_font
        cell.alignment = title_alignment
    for column, width in enumerate(widths, 1):
        sheet.column_dimensions[chr(64 + column)].width = width
    body_alignment = Alignment(vertical="center", wrap_text=False)
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = body_alignment


def write_invoice_workbook(invoice, output_file, overwrite=False):
    output_file = os.path.abspath(output_file)
    if Path(output_file).suffix.lower() != ".xlsx":
        raise ValueError("输出文件必须为 .xlsx 格式。")
    output_parent = os.path.dirname(output_file)
    if not os.path.isdir(output_parent):
        raise ValueError("输出文件夹不存在。")
    if os.path.exists(output_file) and not overwrite:
        raise FileExistsError("输出文件已存在，请选择新的保存位置。")

    workbook = Workbook()
    header_sheet = workbook.active
    header_sheet.title = "发票头信息"
    item_sheet = workbook.create_sheet("明细表")
    validation_sheet = workbook.create_sheet("校验结果")

    header_sheet.append(HEADER_FIELDS)
    header_values = dict(invoice.header)
    header_values["开票日期"] = _date_value(header_values["开票日期"])
    header_values["备注"] = header_values["备注"] or None
    header_sheet.append([_excel_value(header_values[field]) for field in HEADER_FIELDS])
    for column in (12, 13, 14):
        cell = header_sheet.cell(2, column)
        cell.number_format = '0.00' if cell.value == 0 else '#,##0.00;[Red]-#,##0.00;"-"'
    for column in (1, 2, 5, 9):
        header_sheet.cell(2, column).number_format = "@"
        header_sheet.cell(2, column).quotePrefix = True
    header_sheet.cell(2, 3).number_format = "yyyy-mm-dd"

    item_sheet.append(ITEM_FIELDS)
    for item in invoice.items:
        item_sheet.append(
            [
                _excel_value(item.project_name),
                _excel_value(item.specification),
                _excel_value(item.unit),
                _excel_value(item.quantity),
                _excel_value(item.unit_price),
                _excel_value(item.amount),
                _excel_value(item.tax_rate if item.tax_rate is not None else item.tax_rate_text or None),
                _excel_value(item.tax_amount),
            ]
        )
    for row in range(2, item_sheet.max_row + 1):
        item_sheet.cell(row, 4).number_format = "General"
        for column in (5, 6, 8):
            cell = item_sheet.cell(row, column)
            cell.number_format = '0.00####' if cell.value == 0 else '#,##0.00####;[Red]-#,##0.00####;"-"'
        item_sheet.cell(row, 7).number_format = "0.00%"

    validation_sheet.append(VALIDATION_FIELDS)
    for record in invoice.validations:
        validation_sheet.append(
            [
                _excel_value(record.invoice_number),
                record.item_row,
                record.check,
                "异常" if record.abnormal else "正常",
                record.abnormal_fields,
                _excel_value(record.actual),
                _excel_value(record.expected),
                _excel_value(record.difference),
                record.note,
            ]
        )
        status_cell = validation_sheet.cell(validation_sheet.max_row, 4)
        status_cell.fill = PatternFill(
            "solid",
            fgColor="F4CCCC" if record.abnormal else "D9EAD3",
        )
        status_cell.font = Font(color="9C0006" if record.abnormal else "274E13", bold=True)
    for row in range(2, validation_sheet.max_row + 1):
        validation_sheet.cell(row, 1).number_format = "@"
        validation_sheet.cell(row, 1).quotePrefix = True
        for column in (6, 7, 8):
            validation_sheet.cell(row, column).number_format = '#,##0.00;[Red]-#,##0.00;"-"'

    _style_sheet(
        header_sheet,
        (15, 26, 13, 36, 26, 28, 30, 36, 26, 28, 30, 18, 14, 18, 20, 32),
    )
    _style_sheet(item_sheet, (80, 48, 10, 12, 14, 14, 10, 14))
    _style_sheet(
        validation_sheet,
        (26, 11, 30, 12, 30, 16, 16, 14, 28),
    )

    file_descriptor, temporary_file = tempfile.mkstemp(
        prefix=f".{Path(output_file).stem}-",
        suffix=".xlsx",
        dir=output_parent,
    )
    os.close(file_descriptor)
    try:
        workbook.save(temporary_file)
        os.chmod(temporary_file, 0o644)
        if overwrite:
            os.replace(temporary_file, output_file)
        else:
            output_file = publish_output(temporary_file, output_file)
    except Exception:
        try:
            os.unlink(temporary_file)
        except FileNotFoundError:
            pass
        raise
    finally:
        workbook.close()
        Path(temporary_file).unlink(missing_ok=True)
    return output_file


LEDGER_FIELDS = (
    "文件名",
    "发票号码",
    "开票日期",
    "购买方",
    "销售方",
    "金额",
    "税额",
    "价税合计",
    "异常数量",
    "结果文件路径",
    "处理状态",
)


def _ledger_log_path(output_folder):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return available_output_path(Path(output_folder) / f"发票批量汇总日志_{stamp}.txt")


def _write_invoice_ledger_log(log_file, results, failures, ledger_file):
    total_items = sum(result.item_count for result in results)
    total_abnormal = sum(result.abnormal_count for result in results)
    with Path(log_file).open("w", encoding="utf-8") as handle:
        handle.write("发票批量汇总日志\n")
        handle.write(f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n")
        handle.write(f"汇总结果：{ledger_file}\n\n")
        handle.write("匹配结果：\n")
        for result in results:
            status = "已生成，需核对" if result.abnormal_count else "已生成，校验通过"
            handle.write(
                f"{status} "
                f"source_file={result.source_file} "
                f"invoice_number={result.invoice_number} "
                f"seller_name={result.seller_name} "
                f"seller_tax_id={result.seller_tax_id} "
                f"output_file={result.output_file}\n"
            )
        for source_file, error in failures:
            handle.write(f"失败 source_file={source_file} error={error}\n")
        handle.write("\n计算过程：\n")
        handle.write(f"已生成发票数={len(results)}\n")
        handle.write(f"校验通过发票数={sum(result.abnormal_count == 0 for result in results)}\n")
        handle.write(f"需核对发票数={sum(result.abnormal_count > 0 for result in results)}\n")
        handle.write(f"失败发票数={len(failures)}\n")
        handle.write(f"明细行数合计={total_items}\n")
        handle.write(f"校验异常合计={total_abnormal}\n")
        handle.write("\n文件生成状态：\n")
        handle.write(f"summary_file={ledger_file}\n")
        handle.write(f"log_file={log_file}\n")


def write_invoice_ledger(results, failures, output_folder):
    if not results:
        raise ValueError("没有可汇总的发票。")
    output_folder = Path(output_folder).expanduser().resolve()
    output_folder.mkdir(parents=True, exist_ok=True)
    ledger_file = available_output_path(
        output_folder / f"发票批量汇总_{datetime.now():%Y%m%d}.xlsx"
    )

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "发票汇总"
    sheet.append(LEDGER_FIELDS)
    for result in results:
        sheet.append(
            [
                Path(result.source_file or result.output_file).name,
                result.invoice_number,
                _date_value(result.invoice_date),
                result.buyer_name,
                result.seller_name,
                _excel_value(result.amount),
                _excel_value(result.tax_amount),
                _excel_value(result.total_amount),
                result.abnormal_count,
                result.output_file,
                "已生成，需核对" if result.abnormal_count else "已生成，校验通过",
            ]
        )
    _style_sheet(
        sheet,
        [32, 26, 16, 36, 36, 14, 14, 14, 12, 64, 24],
    )
    file_descriptor, temporary_file = tempfile.mkstemp(
        prefix=f".{Path(ledger_file).stem}-",
        suffix=".xlsx",
        dir=output_folder,
    )
    os.close(file_descriptor)
    try:
        workbook.save(temporary_file)
        os.chmod(temporary_file, 0o644)
        ledger_file = publish_output(temporary_file, ledger_file)
    except Exception:
        try:
            os.unlink(temporary_file)
        except FileNotFoundError:
            pass
        raise
    finally:
        workbook.close()
        Path(temporary_file).unlink(missing_ok=True)

    try:
        log_file = _ledger_log_path(output_folder)
        _write_invoice_ledger_log(log_file, results, failures, ledger_file)
    except Exception as error:
        return InvoiceLedgerResult(
            str(ledger_file),
            "",
            f"{type(error).__name__}: {error}",
        )
    return InvoiceLedgerResult(str(ledger_file), str(log_file))


def convert_invoice_pdf(pdf_file, output_file, progress_callback=None, overwrite=False):
    invoice = extract_invoice(pdf_file, progress_callback)
    output_path = Path(output_file)
    if output_path.suffix.lower() != ".xlsx":
        invoice_number = re.sub(
            r"[^0-9A-Z]",
            "",
            str(invoice.header.get("发票号码", "")).upper(),
        )
        if not invoice_number:
            raise ValueError("未能识别发票号码，未生成 Excel。")
        output_path = available_output_path(output_path / f"{invoice_number}.xlsx")
        overwrite = False
    output_file = str(output_path)
    output_file = write_invoice_workbook(invoice, output_file, overwrite=overwrite)
    header = invoice.header
    return PdfInvoiceResult(
        output_file=os.path.abspath(output_file),
        item_count=len(invoice.items),
        abnormal_count=sum(record.abnormal for record in invoice.validations),
        source_file=os.path.abspath(pdf_file),
        invoice_number=header.get("发票号码", ""),
        invoice_date=header.get("开票日期", ""),
        buyer_name=header.get("购买方名称", ""),
        seller_name=header.get("销售方名称", ""),
        seller_tax_id=header.get("销售方税号", ""),
        amount=header.get("合计金额（不含税）"),
        tax_amount=header.get("合计税额"),
        total_amount=header.get("价税合计（小写）"),
    )


def convert_invoice_pdfs(pdf_files, output_folder, progress_callback=None):
    output_folder = os.path.abspath(output_folder)
    if not os.path.isdir(output_folder):
        raise ValueError("Excel 保存文件夹不存在。")

    results = []
    failures = []
    total = len(pdf_files)
    progress_total = max(total * 100, 1)
    for index, pdf_file in enumerate(pdf_files, 1):
        if progress_callback:
            progress_callback(
                (index - 1) * 100,
                progress_total,
                f"正在准备第 {index} / {total} 张：{Path(pdf_file).name}",
            )
        try:
            def page_progress(page, page_total, message):
                if progress_callback:
                    page_fraction = 0
                    if page_total:
                        page_fraction = round(max(0, min(page, page_total)) * 99 / page_total)
                    progress_callback(
                        (index - 1) * 100 + page_fraction,
                        progress_total,
                        f"正在读取第 {index} / {total} 张：{Path(pdf_file).name}（{message}）",
                    )

            results.append(
                convert_invoice_pdf(
                    pdf_file,
                    output_folder,
                    progress_callback=page_progress,
                )
            )
            if progress_callback:
                progress_callback(
                    index * 100,
                    progress_total,
                    f"已完成第 {index} / {total} 张：{Path(pdf_file).name}",
                )
        except Exception as error:
            failures.append((os.path.abspath(pdf_file), str(error)))

    if progress_callback:
        progress_callback(total * 100, progress_total, "批量解析完成")
    return results, failures


def run_invoice_batch_task(source_files, output_folder, result_queue):
    """Run one invoice batch separately so the desktop app can safely stop it."""
    try:
        def progress(value, total, message):
            result_queue.put(("progress", (int(value), int(total), str(message))))

        results, failures = convert_invoice_pdfs(
            source_files,
            output_folder,
            progress_callback=progress,
        )
        ledger_result = None
        ledger_error = ""
        if results:
            progress(
                len(source_files) * 100,
                max(len(source_files) * 100, 1),
                "正在生成发票汇总结果和处理日志…",
            )
            try:
                ledger_result = write_invoice_ledger(results, failures, output_folder)
            except Exception as error:
                ledger_error = str(error)
        result_queue.put(("completed", (results, failures, ledger_result, ledger_error)))
    except Exception as error:
        result_queue.put(("failed", f"{type(error).__name__}: {error}"))
