"""Read-only worksheet review shared by the merge list and its export guard."""
from dataclasses import dataclass
from pathlib import Path

from openpyxl.utils import get_column_letter, range_boundaries


@dataclass(frozen=True)
class MergeSource:
    path: str
    sheet_name: str
    sheet_names: tuple
    header_row: int
    headers: tuple
    preview: tuple
    row_count: int
    column_count: int
    merged_cells: int
    fingerprint: tuple
    issues: tuple
    literal_labels: frozenset
    full_width: int
    has_typed_data: bool


@dataclass(frozen=True)
class MergeCheck:
    ok: bool
    summary: str
    details: tuple = ()


def _header_issues(headers, occupied, row_number, merges, previous, unsafe_cells):
    issues = []
    if not any(headers):
        issues.append(f"第 {row_number} 行没有可核对的字段名，请重新选择表头行。")
    positions = {}
    for idx, name in enumerate(headers, 1):
        letter = get_column_letter(idx)
        if name:
            positions.setdefault(name, []).append(letter)
        elif idx in occupied:
            issues.append(f"{letter} 列下方有数据，但第 {row_number} 行没有字段名。")
    for name, columns in positions.items():
        if len(columns) > 1:
            issues.append(f"{'、'.join(columns)} 列都叫“{name}”，无法区分同名字段。")
    for address in unsafe_cells:
        issues.append(f"{address} 的表头是公式或错误值，请选择包含固定字段名的行。")

    for cell_range in merges:
        left, top, right, bottom = range_boundaries(cell_range)
        # A single merged report title above a row of column names is common.
        # Multiple group labels immediately above it make a single row ambiguous.
        if top <= row_number <= bottom or (
            bottom == row_number - 1 and left < right and len(previous) > 1
        ):
            issues.append(f"表头涉及合并区域 {cell_range}，无法按单行可靠核对字段。")
    return tuple(issues)


def review_worksheet(path, workbook, sheet_name, header_row, metadata, fingerprint):
    worksheet = workbook[sheet_name]
    worksheet.reset_dimensions()  # Ignore stale or over/under-reported XML dimensions.
    previews = []
    occupied = set()
    field_names = {}
    previous = set()
    unsafe_cells = []
    literal_labels = set()
    full_width = 0
    has_typed_data = False
    for number, row in enumerate(worksheet.iter_rows(), 1):
        show = number <= 5 or abs(number - header_row) <= 2
        if show:
            previews.append((number, tuple(
                "" if cell.value is None else str(cell.value) for cell in row
            )))
        for index, cell in enumerate(row, 1):
            value = cell.value
            if value is None or isinstance(value, str) and not value.strip():
                continue
            full_width = max(full_width, index)
            if number < header_row - 1:
                continue
            if number == header_row - 1:
                previous.add(index)
            elif number == header_row:
                field_names[index] = str(value).strip()
                if cell.data_type in ("f", "e"):
                    unsafe_cells.append(cell.coordinate)
                elif isinstance(value, str) and any(ch.isalpha() for ch in value):
                    literal_labels.add(field_names[index])
            else:
                occupied.add(index)
                if cell.data_type in ("n", "d", "f", "b"):
                    has_typed_data = True
    width = max(max(occupied, default=0), max(field_names, default=0))
    headers = tuple(field_names.get(idx, "") for idx in range(1, width + 1))
    issues = _header_issues(headers, occupied, header_row, metadata.merged_ranges,
                            previous, unsafe_cells)
    return MergeSource(path, sheet_name, tuple(sheet.title for sheet in workbook.worksheets),
                       header_row, headers, tuple(previews), metadata.row_count, width,
                       len(metadata.merged_ranges), fingerprint, issues, frozenset(literal_labels),
                       full_width, has_typed_data)


def _column_differences(reference, source):
    expected = reference.headers
    actual = source.headers
    expected_names, actual_names = set(expected), set(actual)
    missing = tuple(name for name in expected if name and name not in actual_names)
    extra = tuple(name for name in actual if name and name not in expected_names)
    details = []
    if missing:
        details.append("缺少字段：" + "、".join(missing))
    if extra:
        details.append("多出字段：" + "、".join(extra))
    changes = 0
    for index in range(max(len(expected), len(actual))):
        left = expected[index] if index < len(expected) else ""
        right = actual[index] if index < len(actual) else ""
        if left == right:
            continue
        changes += 1
        letter = get_column_letter(index + 1)
        if left and right:
            consequence = f"按当前位置合并，“{right}”会写入“{left}”列。"
        elif right:
            consequence = f"结果表的 {letter} 列没有对应“{right}”的表头。"
        else:
            consequence = f"结果表的“{left}”列在此位置没有对应字段。"
        details.append(f"{letter} 列：对照表“{left or '（空）'}”，本表“{right or '（空）'}”。{consequence}")
    if missing or extra:
        problem = "、".join(x for x in ("缺列" if missing else "", "多列" if extra else "") if x)
    else:
        problem = "列顺序不同"
    return MergeCheck(False, f"{problem} · {changes} 处", tuple(details))


def _known_header_mismatch(reference, source):
    if reference.headers == source.headers:
        return False
    shared = reference.literal_labels & source.literal_labels
    if not shared:
        return False
    # If a shared label moved and another label corroborates the two schemas,
    # it is not safe to reinterpret these headers as arbitrary text records.
    base_positions = {label: index for index, label in enumerate(reference.headers)}
    moved = any(label in shared and base_positions[label] != index
                for index, label in enumerate(source.headers))
    if moved and len(shared) >= 2:
        return True
    # Shared labels above numeric/date/formula records give another concrete
    # indication of headings, including a missing/replaced column of equal width.
    return (reference.has_typed_data and source.has_typed_data
            and all(label in reference.literal_labels for label in reference.headers if label)
            and all(label in source.literal_labels for label in source.headers if label))


def compare_merge_sources(sources, headerless=False):
    if not sources:
        return ()
    reference = sources[0]
    checks = []
    for index, source in enumerate(sources):
        if headerless:
            # A repeated set of labels in different positions is a known column
            # mismatch. Different text in two ordinary data rows is not enough.
            if not source.full_width:
                checks.append(MergeCheck(False, "工作表无可核对数据", ("请选择包含数据的工作表。",)))
            elif source.full_width != reference.full_width:
                checks.append(MergeCheck(False, "数据列数不同", (
                    f"对照表有 {reference.full_width} 列，本表有 {source.full_width} 列，请核实。",
                )))
            elif index and _known_header_mismatch(reference, source):
                checks.append(_column_differences(reference, source))
            else:
                checks.append(MergeCheck(True, "无表头 · 按位置合并"))
        elif source.issues:
            checks.append(MergeCheck(False, "无法核对", source.issues))
        elif index == 0:
            checks.append(MergeCheck(True, "对照表"))
        elif reference.issues:
            checks.append(MergeCheck(False, "待核对", ("请先处理第一份参与文件的表头。",)))
        elif reference.headers == source.headers:
            checks.append(MergeCheck(True, "表头一致"))
        else:
            checks.append(_column_differences(reference, source))
    return tuple(checks)


def source_fingerprint(path):
    status = Path(path).stat()
    return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns, status.st_ctime_ns
